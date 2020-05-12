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


def run(consumer, group='recently_viewed', stream='events:article:views'):
    """
    Subscribes to stream and updates the recently viewed sorted set by user/session
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

    ('1587656726037-0', {'article_id': 'article:54a6754d6cfc41f875aa8a644589160c0930423a', 'article_type': 'Help Guide', 'article_title': 'Signing into online banking using the app', 'country': 'ZA', 'platform': 'iOS', 'version': 'v2', 'user_id': '2288', 'session_id': 'f65f9d7f6049e857b5f77c5f45908f0adc68901a2c5b7d287e58e1861a23849e'})
    """
    while True:
        for offset in ['0', '>']:
            for _, entries in redisClient.xreadgroup(
                    group, consumer, {stream: offset}, count=10, block=0):
                for id, entry in entries:
                    print((id, entry))
                    key = ':'.join(['recently_viewed', entry['session_id']])
                    score = id.split('-', maxsplit=1)[0]
                    element = entry['article_id']
                    pipe = redisClient.pipeline(transaction=True)
                    pipe.zadd(key, {element: int(score)})
                    pipe.zremrangebyrank(key, 0, -6)
                    pipe.expire(key, 86400)
                    pipe.execute()
                    redisClient.xack(stream, group, id)


if __name__ == "__main__":
    """
    Example: python recently_viewed_worker.py consumer1
    """
    run(sys.argv[1])
