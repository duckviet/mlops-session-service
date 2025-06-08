# model_validation.py
import mlflow
import logging
from mlflow.tracking import MlflowClient

def validate_model_performance(model_name: str, staging_version: str) -> bool:
    """
    Validate model performance trước khi promote lên production
    """
    try:
        client = MlflowClient()
        
        # Get model metrics
        model_version = client.get_model_version(model_name, staging_version)
        run_id = model_version.run_id
        
        # Get run metrics
        run = client.get_run(run_id)
        metrics = run.data.metrics
        
        # Define validation criteria
        min_sessions = 5  # Minimum sessions trained on
        
        if metrics.get("num_sessions", 0) >= min_sessions:
            logging.info(f"Model validation passed for version {staging_version}")
            return True
        else:
            logging.warning(f"Model validation failed for version {staging_version}")
            return False
            
    except Exception as e:
        logging.error(f"Model validation error: {e}")
        return False

def auto_promote_validated_models():
    """
    Tự động promote models đã validate thành công
    """
    client = MlflowClient()
    try:
        staging_models = client.get_latest_versions("lgbm_ranker", stages=["Staging"])
        
        for model in staging_models:
            if validate_model_performance("lgbm_ranker", model.version):
                # Promote to production
                client.transition_model_version_stage(
                    name="lgbm_ranker",
                    version=model.version,
                    stage="Production"
                )
                logging.info(f"Auto-promoted model version {model.version} to Production")
                
    except Exception as e:
        logging.error(f"Auto-promotion failed: {e}") 
