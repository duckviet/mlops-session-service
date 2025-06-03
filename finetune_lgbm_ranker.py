# finetune_lgbm_ranker.py
import polars as pl
import json
import logging
import shutil
from pathlib import Path
from lightgbm import LGBMRanker
import joblib
from process_pipeline import apply, pipeline, get_session_lenghts
import mlflow
import mlflow.lightgbm
from datetime import datetime
import os

def load_and_preprocess_kafka_data(events_file_path):
    """
    Load và preprocess dữ liệu từ file JSON events.json (từ Kafka)
    """
    logging.info(f"Loading data from {events_file_path}")

    with open(events_file_path, 'r') as f:
        raw_events = json.load(f)

    if not raw_events:
        raise ValueError("No events found in the file")

    # Chuyển đổi dữ liệu từ Kafka format thành DataFrame
    processed_data = []

    for session_data in raw_events:
        session_id = int(session_data['session_id'])
        events = session_data['events']

        for i, event in enumerate(events):
            processed_data.append({
                'session': session_id,
                'aid': event['aid'],
                'ts': event['ts'],
                'type': event['type'],
                'action_num_reverse_chrono': len(events) - i - 1  # Reverse chronological order
            })

    if not processed_data:
        raise ValueError("No processed data available")

    # Tạo DataFrame từ processed data
    df = pl.DataFrame(processed_data)

    # Cast types để đảm bảo consistency
    df = df.with_columns([
        pl.col('session').cast(pl.Int64),
        pl.col('aid').cast(pl.Int32),
        pl.col('ts').cast(pl.Int64),
        pl.col('type').cast(pl.UInt8),
        pl.col('action_num_reverse_chrono').cast(pl.Int32)
    ])

    logging.info(f"Processed {len(df)} events from {len(raw_events)} sessions")
    return df

def create_training_labels(df):
    """
    Tạo training labels từ dữ liệu events
    Sử dụng heuristic: orders (type=2) > carts (type=1) > clicks (type=0)
    """
    # Tạo ground truth dựa trên type của event
    # Orders có priority cao nhất (3), carts (2), clicks (1)
    type_weights = {0: 1, 1: 2, 2: 3}  # clicks, carts, orders

    labels = df.with_columns([
        pl.col('type').replace_strict(type_weights, default=1).alias('gt')
    ]).select(['session', 'type', 'aid', 'gt'])

    return labels

def copy_model_safely(source_path, dest_path):
    """
    Safely copy model from source to destination with error handling
    """
    try:
        # Create destination directory if it doesn't exist
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Copy the file
        shutil.copy2(source_path, dest_path)
        logging.info(f"Successfully copied model from {source_path} to {dest_path}")
        return True
    except PermissionError as e:
        logging.warning(f"Permission denied copying to {dest_path}: {e}")
        return False
    except Exception as e:
        logging.warning(f"Failed to copy model to {dest_path}: {e}")
        return False

def load_existing_model_safely(model_path):
    """
    Safely load existing model with multiple fallback locations
    """
    # Try different possible locations for the existing model
    possible_paths = [
        model_path,
        f"/tmp/{Path(model_path).name}",
        f"/opt/airflow/model/{Path(model_path).name}",
        f"model/{Path(model_path).name}"
    ]
    
    for path in possible_paths:
        if Path(path).exists():
            try:
                logging.info(f"Attempting to load model from {path}")
                model = joblib.load(path)
                logging.info(f"Successfully loaded existing model from {path}")
                return model
            except Exception as e:
                logging.warning(f"Failed to load model from {path}: {e}")
                continue
    
    logging.info("No existing model found in any location")
    return None

def train_or_finetune_model(train_df, model_path=None, save_path='model/lgbm_ranker.joblib', force_retrain=False):
    """
    Train mô hình mới hoặc fine-tune mô hình có sẵn.
    Sử dụng /tmp làm primary storage để tránh permission issues.
    """
    logging.info("Starting model training/fine-tuning...")

    # Apply preprocessing pipeline
    train_processed = apply(train_df.clone(), pipeline)
    
    # Tạo labels
    train_labels = create_training_labels(train_processed)

    # Join với labels
    train_final = train_processed.join(
        train_labels,
        how='left',
        on=['session', 'type', 'aid']
    ).with_columns(pl.col('gt').fill_null(0))

    # Lấy session lengths
    session_lengths = get_session_lenghts(train_final)

    # Feature columns
    feature_cols = [
        'aid', 'type', 'action_num_reverse_chrono',
        'session_length', 'log_recency_score', 'type_weighted_log_recency_score'
    ]
    target = 'gt'

    # Khởi tạo ranker là None
    ranker = None

    # MLflow experiment setup với fallback
    experiment_name = "lgbm_ranker_training"
    use_mlflow = True
    
    try:
        mlflow.set_experiment(experiment_name)
        logging.info("MLflow connection successful")
    except Exception as e:
        logging.warning(f"MLflow connection failed: {e}. Continuing without MLflow tracking.")
        use_mlflow = False
    
    # Start MLflow run với try-catch
    mlflow_run = None
    if use_mlflow:
        try:
            mlflow_run = mlflow.start_run(run_name=f"training_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            # Log parameters
            mlflow.log_param("force_retrain", force_retrain)
            mlflow.log_param("feature_columns", feature_cols)
            mlflow.log_param("target_column", target)
            mlflow.log_param("num_sessions", len(train_final['session'].unique()))
            mlflow.log_param("num_events", len(train_final))
        except Exception as e:
            logging.warning(f"Failed to start MLflow run: {e}")
            use_mlflow = False

    try:
        # Check if we should fine-tune existing model
        if not force_retrain and model_path:
            ranker = load_existing_model_safely(model_path)
            
            if ranker is not None:
                # For fine-tuning, we can train with fewer estimators
                if hasattr(ranker, 'n_estimators'):
                    ranker.set_params(n_estimators=ranker.n_estimators + 10)
                    logging.info("Configured model for fine-tuning")
                    if use_mlflow:
                        try:
                            mlflow.log_param("fine_tuning", True)
                            mlflow.log_param("n_estimators", ranker.n_estimators)
                        except Exception as e:
                            logging.warning(f"Failed to log MLflow params: {e}")
                else:
                    logging.warning("Loaded model does not have 'n_estimators' attribute. Cannot fine-tune directly.")
                    ranker = None

        # Create new model if no existing model or loading failed or force_retrain is True
        if ranker is None:
            if force_retrain:
                logging.info("Force retraining enabled. Training new model from scratch.")
            else:
                logging.info("No existing model found or loading failed. Training new model from scratch.")
            
            # Default parameters
            params = {
                "objective": "lambdarank",
                "metric": "ndcg",
                "boosting_type": "dart",
                "n_estimators": 20,
                "importance_type": 'gain',
                "random_state": 42
            }
            
            # Log parameters if MLflow available
            if use_mlflow:
                try:
                    mlflow.log_params(params)
                except Exception as e:
                    logging.warning(f"Failed to log MLflow params: {e}")
            
            ranker = LGBMRanker(**params)

        # Train the model
        logging.info("Fitting the model...")
        
        # Kiểm tra xem train_final có đủ cột tính năng không
        missing_features = [col for col in feature_cols if col not in train_final.columns]
        if missing_features:
            logging.error(f"Missing feature columns in train_final: {missing_features}. Cannot train model.")
            raise ValueError(f"Missing feature columns: {missing_features}")

        # Train with optional MLflow tracking
        if use_mlflow:
            try:
                mlflow.lightgbm.autolog()
            except Exception as e:
                logging.warning(f"Failed to enable MLflow autolog: {e}")
                
        ranker.fit(
            train_final[feature_cols].to_pandas(),
            train_final[target].to_pandas(),
            group=session_lengths,
        )
        logging.info("Model fitting completed.")

        # Log feature importance if MLflow available
        if use_mlflow:
            try:
                feature_importance = dict(zip(feature_cols, ranker.feature_importances_))
                mlflow.log_dict(feature_importance, "feature_importance.json")
                mlflow.lightgbm.log_model(ranker, "model")
            except Exception as e:
                logging.warning(f"Failed to log to MLflow: {e}")

        # Save to /tmp first (should always work)
        tmp_model_path = f"/tmp/{Path(save_path).name}"
        joblib.dump(ranker, tmp_model_path)
        logging.info(f"Model saved to temporary location: {tmp_model_path}")

        # Try to copy to the intended location
        copy_success = copy_model_safely(tmp_model_path, save_path)
        
        # Also try to copy to other common locations for accessibility
        backup_locations = [
            "/opt/airflow/model/lgbm_ranker.joblib",
            "/tmp/lgbm_ranker_backup.joblib"
        ]
        
        for backup_path in backup_locations:
            if backup_path != save_path:  # Don't duplicate if same path
                copy_model_safely(tmp_model_path, backup_path)

        if copy_success:
            logging.info(f"Model successfully saved to intended location: {save_path}")
        else:
            logging.warning(f"Model saved to temporary location only: {tmp_model_path}")
            logging.warning("The model will be available for this session but may not persist after container restart")

        return ranker
        
    finally:
        # End MLflow run if it was started
        if use_mlflow and mlflow_run:
            try:
                mlflow.end_run()
            except Exception as e:
                logging.warning(f"Failed to end MLflow run: {e}")
                
                
def main():
    """Main function để chạy training pipeline"""
    try:
        # Set MLflow tracking URI from environment variable
        mlflow_tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "file:./mlruns")
        mlflow.set_tracking_uri(mlflow_tracking_uri)
        logging.info(f"Using MLflow tracking URI: {mlflow_tracking_uri}")
        
        # Paths - use /opt/models as primary to match deployment structure
        events_file = 'data/events.json'
        existing_model_path = '/opt/models/lgbm_ranker_current.joblib'
        new_model_path = '/opt/models/lgbm_ranker.joblib'  # Primary save location
        
        # Alternative paths to try for saving
        alternative_save_paths = [
            '/opt/models/lgbm_ranker_current.joblib',  # Update current symlink
            '/opt/airflow/model/lgbm_ranker.joblib'    # Backup location
        ]

        # Load and preprocess data from Kafka
        train_df = load_and_preprocess_kafka_data(events_file)

        # Train or fine-tune model
        model = train_or_finetune_model(
            train_df,
            model_path=existing_model_path,
            save_path=new_model_path,
            force_retrain=True
        )

        # Try to save to alternative locations for persistence
        for alt_path in alternative_save_paths:
            copy_model_safely(new_model_path, alt_path)

        logging.info("Training completed successfully!")
        logging.info(f"Primary model location: {new_model_path}")

        # Print some info about the model
        if hasattr(model, 'feature_importances_'):
            feature_cols = [
                'aid', 'type', 'action_num_reverse_chrono',
                'session_length', 'log_recency_score', 'type_weighted_log_recency_score'
            ]
            importance_df = pl.DataFrame({
                'feature': feature_cols,
                'importance': model.feature_importances_
            }).sort('importance', descending=True)
            logging.info(f"Feature importances:\n{importance_df}")

        # Log model file locations for debugging
        model_locations = [
            '/opt/models/lgbm_ranker.joblib',
            '/opt/models/lgbm_ranker_current.joblib',
            '/opt/airflow/model/lgbm_ranker.joblib'
        ]
        
        logging.info("Checking model file locations:")
        for location in model_locations:
            if Path(location).exists():
                size = Path(location).stat().st_size
                logging.info(f"  ✓ {location} (size: {size} bytes)")
            else:
                logging.info(f"  ✗ {location} (not found)")

    except Exception as e:
        logging.error(f"Training failed: {e}")
        raise

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
