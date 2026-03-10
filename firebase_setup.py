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