"""
Maestro Orchestrator - Anti-fragile workflow engine
Architecture Choice: State machine pattern for campaign lifecycle
Critical: All state transitions are validated and persisted to Firestore
"""
import time
import schedule
import threading
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Any, Optional, List
import logging

from firebase_setup import FirestoreCollections, firebase_manager
from generate_music import AdaptiveMusicGenerator
from processor import AudioValidator
from distribution_manager import AntiFragileUploader

logger = logging.getLogger(__name__)

class CampaignState(str, Enum):
    """Campaign lifecycle states"""
    DRAFT = "draft"
    GENERATING = "generating"
    QA_PENDING = "qa_pending"
    GOLDEN_EAR_TEST = "golden_ear_test"
    DISTRIBUTING = "distributing"
    MONITORING = "monitoring"
    LEARNING = "learning"
    ARCHIVED = "archived"
    FAILED = "failed"

class MaestroOrchestrator:
    """Main orchestrator for the Living Soundscape Engine"""
    
    def __init__(self, campaign_id: Optional[str] = None):
        """
        Initialize orchestrator for a campaign
        
        Args:
            campaign_id: Optional existing campaign ID. If None, creates new campaign.
        """
        self.campaign_id = campaign_id or self._generate_campaign_id()
        self.music_generator = AdaptiveMusicGenerator()
        self.audio_validator = AudioValidator()
        self.distributor = AntiFragileUploader()
        self.is_running = False
        self.thread_lock = threading.Lock()
        
        # Initialize campaign if not exists
        if not self._campaign_exists():
            self._initialize_campaign()
    
    def _generate_campaign_id(self) -> str:
        """Generate unique campaign ID"""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        return f"campaign_{timestamp}"
    
    def _campaign_exists(self) -> bool:
        """Check if campaign exists in Firestore"""
        doc = firebase_manager.read_document(
            FirestoreCollections.CAMPAIGNS,
            self.campaign_id
        )
        return doc is not None
    
    def _initialize_campaign(self) -> None:
        """Initialize new campaign with default strategy"""
        campaign_data = {
            'id': self.campaign_id,
            'state': CampaignState.DRAFT.value,
            'created_at': datetime.utcnow().isoformat(),
            'strategy': {
                'bpm_range': [60, 80],
                'duration_minutes': 45,
                'mood_profile': {"calm": 0.8, "engaging": 0.2},
                'variation_count': 3,
                'target_platforms': ['spotify', 'apple_music'],
                'target_playlists': ['Sleep', 'Study', 'Chill']
            },
            'performance_history': [],
            'generated_tracks': [],
            'errors': []
        }
        
        success = firebase_manager.write_document(
            FirestoreCollections.CAMPAIGNS,
            self.campaign_id,
            campaign_data
        )
        
        if success:
            logger.info(f"Created new campaign: {self.campaign_id}")
        else:
            logger.error(f"Failed to create campaign: {self.campaign_id}")
            raise RuntimeError("Campaign initialization failed")
    
    def start_campaign_cycle(self) -> bool:
        """Execute full campaign lifecycle"""
        try:
            logger.info(f"Starting campaign cycle: {self.campaign_id}")
            
            # 1. GENERATE
            if not self._execute_generation_phase():
                logger.error("Generation phase failed")
                firebase_manager.update_campaign_state(
                    self.campaign_id,
                    CampaignState.FAILED.value,
                    {'phase': 'generation'}
                )
                return False
            
            # 2. VALIDATE
            if not self._execute_validation_phase():
                logger.error("Validation phase failed")
                firebase_manager.update_campaign_state(
                    self.campaign_id,
                    CampaignState.FAILED.value,
                    {'phase': 'validation'}
                )
                return False
            
            # 3. DISTRIBUTE
            if not self._execute_distribution_phase():
                logger.error("Distribution phase failed")
                firebase_manager.update_campaign_state(
                    self.campaign_id,
                    CampaignState.FAILED.value,
                    {'phase': 'distribution'}
                )
                return False
            
            # 4. MONITOR
            self._schedule_monitoring()
            
            logger.info(f"Campaign cycle completed: {self.campaign_id}")
            return True
            
        except Exception as e:
            logger.error(f"Campaign cycle failed: {str(e)}", exc_info=True)
            firebase_manager.update_campaign_state(
                self.campaign_id,
                CampaignState.FAILED.value,
                {'error': str(e)}
            )
            return False
    
    def _execute_generation_phase(self) -> bool:
        """Execute music generation with strategy adaptation"""
        logger.info("Starting generation phase")
        
        # Get current strategy
        campaign_data = firebase_manager.read_document(
            FirestoreCollections.CAMPAIGNS,
            self.campaign_id
        )
        
        if not campaign_data:
            logger.error("Campaign data not found")
            return False
        
        # Update state
        firebase_manager.update_campaign_state(
            self.campaign_id,
            CampaignState.GENERATING.value
        )
        
        # Generate with adaptive strategy
        strategy = campaign_data.get('strategy', {})
        previous_performance = campaign_data.get('performance_history', [])
        
        if previous_performance:
            # Incorporate learning from past performance
            strategy['previous_performance'] = previous_performance[-1]  # Latest
            
        try:
            generation_result = self.music_generator.generate_with_strategy(strategy)
            
            # Store generated tracks
            track_ids = []
            for i, track in enumerate(generation_result.get('tracks', [])):
                track_id = f"{self.campaign_id}_track_{i}"
                track_data = {
                    'campaign_id': self.campaign_id,
                    'track_id': track_id,
                    'audio_path': track['path'],
                    'metadata': track['metadata'],
                    'generated_at': datetime.utcnow().isoformat(),
                    'validation_status': 'pending'
                }
                
                firebase_manager.write_document(
                    FirestoreCollections.TRACKS,
                    track_id,
                    track_data
                )
                track_ids.append(track_id)
            
            # Update campaign with track references
            firebase_manager.write_document(
                FirestoreCollections.CAMPAIGNS,
                self.campaign_id,
                {'generated_tracks': track_ids},
                merge=True
            )
            
            logger.info(f"Generated {len(track_ids)} tracks")
            return True
            
        except Exception as e:
            logger.error(f"Generation failed: {e}")
            return False
    
    def _execute_validation_phase(self) -> bool:
        """Validate audio quality and perceptual metrics"""
        logger.info("Starting validation phase")
        
        firebase_manager.update_campaign_state(
            self.campaign_id,
            CampaignState.QA_PENDING.value
        )
        
        # Get generated tracks
        campaign_data = firebase_manager.read_document(
            FirestoreCollections.CAMPAIGNS,
            self.campaign_id
        )
        
        if not campaign_data:
            return False
        
        track_ids = campaign_data.get('generated_tracks', [])
        validation_results = []
        
        for track_id in track_ids:
            track_data = firebase_manager.read_document(
                FirestoreCollections.TRACKS,
                track_id
            )
            
            if not track_data:
                logger.warning(f"Track not found: {track_id}")
                continue
            
            audio_path = track_data.get('audio_path')
            if not