from dotenv import load_dotenv
load_dotenv()

# Override to fast/reliable model before handlers.agent is imported
import config
config.AGENT_MODEL = "nvidia/nemotron-3-nano-30b-a3b:free"
