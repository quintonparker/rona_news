import redis
import os
import sys
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv('REDIS_URL')

if REDIS_URL.startswith('rediss'):
    redisClient = redis.from_url(REDIS_URL, decode_responses=True,
                                 ssl_cert_reqs=None)
else:
    redisClient = redis.from_url(REDIS_URL, decode_responses=True)


def run(consumer, group='search_analytics', stream='events:search:clicks'):
    """
    Subscribe to click events and updates the analytics search index
    """
    print(f'Starting {group}/{consumer} consumer listen on {stream}')
    try:
        redisClient.xgroup_create(stream, group, id='0', mkstream=True)
    except redis.exceptions.ResponseError as error:
        print(error)
        if not str(error) == 'BUSYGROUP Consumer Group name already exists':
            raise error

    """
    Sample (id, entry) tuple

    ('1589288439508-0', {'_version': 'v1', 'search_id': '1589288437521-0', 'position': '2', 'article_id': '5857', 'ip': '172.25.0.1', 'user_id': '', 'session_id': 'bb1ee16a3eb745be8d9fcf71d55c3a80'})
    """
    while True:
        for offset in ['0', '>']:
            for _, entries in redisClient.xreadgroup(
                    group, consumer, {stream: offset}, count=10, block=0):
                for id, entry in entries:
                    print((id, entry))
                    docId = ('query:%s' % entry['search_id'])
                    key = ('clicks:%s' % entry['search_id'])
                    pipe = redisClient.pipeline(transaction=True)
                    pipe.incr(key)
                    pipe.expire(key, 3600)
                    results = pipe.execute()
                    print((docId, key, results))
                    redisClient.hset(f'analytics:search:{docId}', "clicks", int(results[0]))
                    redisClient.xack(stream, group, id)


if __name__ == "__main__":
    """
    Example: python search_analytics_clicks_worker.py consumer1
    """
    run(sys.argv[1])
