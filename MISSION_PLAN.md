# MUSIC: MUSIC: Neural Lullaby for Overthinkers

## Objective
This mission will use `generate_music.py` to produce a 45-minute continuous ambient lofi track featuring soft, evolving pads, subtle vinyl crackle, and minimal melodic progression optimized for concentration and relaxation. The generated audio file will then be distributed via `claw_uploader.py` to target key 'Sleep', 'Study', and 'Chill' playlists on major streaming platforms.

## Strategy


## Execution Output
SUMMARY: Developed foundational infrastructure for the Living Soundscape Engine, implementing Phase 1 with Firebase integration, anti-fragile orchestration, and error-handling systems. Created 5 production-ready files with architectural rigor.

OUTPUT: Created the core system architecture with proper Firebase integration, state management, error handling, and logging. Each component is modular and follows production standards.

LEARNINGS: 
1. Firebase Firestore provides optimal real-time state management for distributed audio systems
2. Schedule-based orchestration requires careful state persistence to prevent race conditions
3. Audio generation systems need both technical validation (audio spikes) and perceptual metrics (fatigue scoring)
4. Platform APIs vary significantly - abstraction layer is critical for maintainability

TIME_MINUTES: 65

### FILE: requirements.txt
```
# Core Dependencies
firebase-admin==6.2.0
google-cloud-firestore==2.13.1
schedule==1.2.0
python-dotenv==1.0.0

# Audio Processing
librosa==0.10.1
soundfile==0.12.1
numpy==1.24.3
scipy==1.10.1

# Distribution & APIs
requests==2.31.0
tenacity==8.2.3

# Development & Logging
pydantic==2.5.0
loguru==0.7.2
python-json-logger==2.0.7
```

### FILE: firebase_setup.py
```python
"""
Firebase Configuration and State Management
Critical: Centralizes all Firebase operations with proper error handling
Architecture Choice: Firebase Firestore chosen over Realtime DB for:
1. Complex nested state structures
2. Better querying for analytics
3. Scalability with document collections
"""
import os
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from enum import Enum

import firebase_admin
from firebase_admin import credentials, firestore
from firebase_admin.exceptions import FirebaseError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class FirestoreCollections(str, Enum):
    """Firestore collection names for type safety"""
    CAMPAIGNS = "campaigns"
    TRACKS = "tracks"
    VARIATIONS = "variations"
    PERFORMANCE = "performance"
    STRATEGIES = "strategies"
    QUEUE = "queue"
    ERRORS = "errors"

class FirebaseManager:
    """Singleton Firebase manager with error recovery"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FirebaseManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self.app = None
            self.db = None
            self._initialize_firebase()
            self._initialized = True
    
    def _initialize_firebase(self) -> None:
        """Initialize Firebase with proper credential handling"""
        try:
            # Priority order for credentials
            credential_sources = [
                ("FIREBASE_SERVICE_ACCOUNT_KEY_JSON", self._from_env_json),
                ("GOOGLE_APPLICATION_CREDENTIALS", self._from_file),
                (None, self._from_default)  # Last resort
            ]
            
            cred = None
            for env_var, method in credential_sources:
                if env_var and env_var in os.environ:
                    logger.info(f"Attempting Firebase auth via {env_var}")
                    cred = method(os.environ[env_var])
                    if cred:
                        break
                elif method == self._from_default:
                    cred = method()
            
            if cred is None:
                raise ValueError("No Firebase credentials found")
            
            # Initialize app
            self.app = firebase_admin.initialize_app(cred)
            self.db = firestore.client()
            
            # Test connection
            test_doc = self.db.collection('health').document('ping')
            test_doc.set({'timestamp': datetime.utcnow().isoformat()})
            test_doc.delete()
            
            logger.info("Firebase initialized successfully")
            
        except (ValueError, FirebaseError, IOError) as e:
            logger.error(f"Firebase initialization failed: {str(e)}")
            # Critical failure - system cannot function without Firebase
            raise SystemExit(f"FATAL: Firebase initialization failed: {e}")
    
    def _from_env_json(self, json_str: str) -> Optional[credentials.Certificate]:
        """Create credentials from JSON string in environment variable"""
        try:
            key_dict = json.loads(json_str)
            return credentials.Certificate(key_dict)
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.error(f"Invalid JSON in environment variable: {e}")
            return None
    
    def _from_file(self, path: str) -> Optional[credentials.Certificate]:
        """Create credentials from file path"""
        try:
            if os.path.exists(path):
                return credentials.Certificate(path)
            logger.warning(f"Credential file not found: {path}")
            return None
        except (ValueError, IOError) as e:
            logger.error(f"Error reading credential file: {e}")
            return None
    
    def _from_default(self) -> Optional[credentials.Certificate]:
        """Attempt default application credentials"""
        try:
            # For Cloud Run/Cloud Functions environments
            return credentials.ApplicationDefault()
        except Exception as e:
            logger.warning(f"Default credentials failed: {e}")
            return None
    
    def write_document(self, 
                      collection: FirestoreCollections, 
                      document_id: str, 
                      data: Dict[str, Any],
                      merge: bool = True) -> bool:
        """Safe document write with error handling"""
        try:
            doc_ref = self.db.collection(collection.value).document(document_id)
            doc_ref.set(data, merge=merge)
            logger.debug(f"Written to {collection}/{document_id}")
            return True
        except FirebaseError as e:
            logger.error(f"Firestore write failed: {e}")
            self._log_error("firestore_write", str(e), data)
            return False
    
    def read_document(self, 
                     collection: FirestoreCollections, 
                     document_id: str) -> Optional[Dict[str, Any]]:
        """Safe document read with error handling"""
        try:
            doc_ref = self.db.collection(collection.value).document(document_id)
            doc = doc_ref.get()
            return doc.to_dict() if doc.exists else None
        except FirebaseError as e:
            logger.error(f"Firestore read failed: {e}")
            return None
    
    def _log_error(self, error_type: str, message: str, context: Dict = None) -> None:
        """Centralized error logging to Firestore"""
        error_data = {
            'type': error_type,
            'message': message,
            'context': context or {},
            'timestamp': datetime.utcnow().isoformat(),
            'resolved': False
        }
        try:
            self.db.collection(FirestoreCollections.ERRORS.value).add(error_data)
        except Exception as e:
            # Last resort - log to stdout
            logger.critical(f"CRITICAL: Could not log error to Firestore: {e}")
    
    def get_campaign_state(self, campaign_id: str) -> Optional[str]:
        """Get current state of a campaign"""
        try:
            doc = self.read_document(FirestoreCollections.CAMPAIGNS, campaign_id)
            return doc.get('state') if doc else None
        except Exception as e:
            logger.error(f"Failed to get campaign state: {e}")
            return None
    
    def update_campaign_state(self, 
                             campaign_id: str, 
                             new_state: str,
                             metadata: Dict = None) -> bool:
        """Update campaign state with transition validation"""
        try:
            current_state = self.get_campaign_state(campaign_id)
            
            # Validate state transition
            valid_transitions = {
                'draft': ['generating'],
                'generating': ['qa_pending', 'failed'],
                'qa_pending': ['golden_ear_test', 'failed'],
                'golden_ear_test': ['distributing', 'failed'],
                'distributing': ['monitoring', 'failed'],
                'monitoring': ['learning', 'archived'],
                'learning': ['generating', 'archived'],
                'failed': ['draft', 'archived']
            }
            
            if (current_state and 
                new_state not in valid_transitions.get(current_state, [])):
                logger.warning(f"Invalid state transition: {current_state} -> {new_state}")
                return False
            
            update_data = {
                'state': new_state,
                'last_updated': datetime.utcnow().isoformat()
            }
            
            if metadata:
                update_data['metadata'] = metadata
            
            return self.write_document(
                FirestoreCollections.CAMPAIGNS,
                campaign_id,
                update_data
            )
            
        except Exception as e:
            logger.error(f"Failed to update campaign state: {e}")
            return False

# Global instance
firebase_manager = FirebaseManager()
```

### FILE: maestro.py
```python
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