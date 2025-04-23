import utils.env_utils as env_utils
import utils.config_reader_utils as configReader

config = configReader.readConfig(env_utils.get_config_path())
providers = configReader.getProviders(config)

def getModels():
    modelList = []
    customModelList = []
    for provider in providers:
        models = configReader.getModelsinProvider(provider)
        
        for model in models:
            if isinstance(model, str):
                # print("Model: ", model)
                modelList.append(model)
            
            if isinstance(model, dict):
                # print(f"Alias: {model.get('alias')} Upstream: {model.get('upstream_model')}")
                # print(f"custom_params:{model.get('custom_params')}")
                customModelList.append(model)
    return {"models": modelList, "custom_models": customModelList}


