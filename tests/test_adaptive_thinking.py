import asyncio
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.messages import PartStartEvent, PartDeltaEvent
from pydantic_ai import (
    PartStartEvent,
    PartDeltaEvent,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
)

provider = AnthropicProvider(
    api_key='sk-ant-oat01-7rnl9PHKbR2Ga2u9IctT5yvPQi1BaBjI',
    base_url='https://gpt.mirbuds.com/claudecode',
)
model = AnthropicModel('claude-sonnet-4-20250514', provider=provider)
settings = AnthropicModelSettings(max_tokens=16000, anthropic_thinking={'type': 'adaptive'})

agent = Agent(model, model_settings=settings, system_prompt='You are a helpful assistant.')

async def main():
    print('--- Testing adaptive thinking ---')
    async with agent.iter('Given RSA public key with n=323 and e=5, encrypt the message m=100. Then explain how you would decrypt it if you knew the factorization of n.') as run:
        async for node in run:
            if Agent.is_model_request_node(node):
                async with node.stream(run.ctx) as stream:
                    async for event in stream:
                        if isinstance(event, PartStartEvent) and isinstance(event.part, ThinkingPart):
                            print('[THINKING START]')
                        elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, ThinkingPartDelta):
                            if event.delta.content_delta:
                                print(event.delta.content_delta, end='', flush=True)
                        elif isinstance(event, PartStartEvent):
                            print('\n[TEXT START]')
                        elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                            print(event.delta.content_delta, end='', flush=True)
    print('\n--- Done ---')

asyncio.run(main())
