import asyncio, sys, json, httpx
sys.path.insert(0, '/Users/vicevirus/Downloads/discord-bot')
from dotenv import load_dotenv
load_dotenv('/Users/vicevirus/Downloads/discord-bot/.env')
from config import TWITTER_AUTH_TOKEN, TWITTER_CT0

print('Auth token set:', bool(TWITTER_AUTH_TOKEN))
print('CT0 set:', bool(TWITTER_CT0))

BEARER = 'Bearer AAAAAAAAAAAAAAAAAAAAAFXzAwAAAAAAMHCxpeSDG1gLNLghVe8d74hl6k4%3DRUMF4xAQLsbeBhTSRrCiQpJtxoGWeyHrDb5te2jpGskWDFW82F'
URL = 'https://x.com/i/api/graphql/bshMIjqDk8LTXTq4w91WKw/SearchTimeline'
FEATURES = json.dumps({
    'responsive_web_graphql_exclude_directive_enabled': True,
    'responsive_web_graphql_timeline_navigation_enabled': True,
    'longform_notetweets_consumption_enabled': True,
    'freedom_of_speech_not_reach_fetch_enabled': True,
    'standardized_nudges_misinfo': True,
    'tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled': True,
    'longform_notetweets_rich_text_read_enabled': True,
    'responsive_web_enhance_cards_enabled': False,
    'view_counts_everywhere_api_enabled': True,
    'graphql_is_translatable_rweb_tweet_is_translatable_enabled': True,
    'creator_subscriptions_tweet_preview_api_enabled': True,
})
variables = json.dumps({
    'rawQuery': 'malaysia CTF hacking',
    'count': 5,
    'querySource': 'typed_query',
    'product': 'Latest',
    'withDownvotePerspective': False,
    'withReactionsMetadata': False,
    'withReactionsPerspective': False,
})
headers = {
    'authorization': BEARER,
    'cookie': f'auth_token={TWITTER_AUTH_TOKEN}; ct0={TWITTER_CT0}',
    'x-csrf-token': TWITTER_CT0,
    'x-twitter-auth-type': 'OAuth2Session',
    'x-twitter-active-user': 'yes',
    'x-twitter-client-language': 'en',
    'accept': '*/*',
    'accept-language': 'en-US,en;q=0.9',
    'origin': 'https://x.com',
    'referer': 'https://x.com/search',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-site',
}

async def test():
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as c:
        resp = await c.get(URL, headers=headers, params={'variables': variables, 'features': FEATURES})
    print('Status:', resp.status_code)
    data = resp.json()
    instructions = data['data']['search_by_raw_query']['search_timeline']['timeline']['instructions']
    count = 0
    for inst in instructions:
        for entry in inst.get('entries', []):
            item = entry.get('content', {}).get('itemContent', {})
            if item.get('itemType') != 'TimelineTweet':
                continue
            r = item.get('tweet_results', {}).get('result', {})
            if r.get('__typename') == 'TweetWithVisibilityResults':
                r = r.get('tweet', {})
            legacy = r.get('legacy', {})
            user_result = r.get('core', {}).get('user_results', {}).get('result', {})
            user_core = user_result.get('core', {})
            screen_name = user_core.get('screen_name') or user_result.get('legacy', {}).get('screen_name', '?')
            if legacy.get('full_text'):
                count += 1
                print(f"@{screen_name} [{legacy.get('created_at', '')}]")
                print(legacy['full_text'][:150])
                print()
    print(f'Total tweets: {count}')

asyncio.run(test())
