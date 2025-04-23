import yaml


def readConfig(config_file_path):
    with open(config_file_path, 'r') as config_file:
        try:
            return yaml.safe_load(config_file)
        except FileNotFoundError:
            print(f"Error: Configuration file not found at {config_path}")
        except yaml.YAMLError as e:
            print(f"Error parsing YAML file: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
        
        

def getProviders(configyaml):
    if configyaml and "providers" in configyaml:
        return configyaml["providers"]
    
def getModelsinProvider(provider):
    if provider and "models" in provider:
        return provider["models"]
     



