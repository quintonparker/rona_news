import redis
import os
import sys
import uuid
import math
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv('REDIS_URL')

if REDIS_URL.startswith('rediss'):
    redisClient = redis.from_url(REDIS_URL, decode_responses=True,
                                 ssl_cert_reqs=None)
else:
    redisClient = redis.from_url(REDIS_URL, decode_responses=True)


def run(start='-', end='+', stream='events:article:views'):
    """
    Regenerates the popular articles sorted set

    start is a Redis Streams compatible value for expressing the start of a range
    end is a Redis Streams compatible value for expressing the end of a range
    stream is the name of the stream to read
    """
    print(f'Running XRANGE {stream} {start} {end}')

    # build a unique temporary key for the new popular_articles key
    key = ':'.join(['{popular_articles}', uuid.uuid4().hex])

    def generateLeaderboard():
        count = 0
        offset = start
        while True:
            for id, entry in redisClient.xrange(stream, offset, end):
                print((id, entry))
                """
                Sample stream (id, entry) tuple

                ('1587656726037-0', {'article_id': 'article:54a6754d6cfc41f875aa8a644589160c0930423a', 'article_type': 'Help Guide', 'article_title': 'Signing into online banking using the app', 'country': 'ZA', 'platform': 'iOS', 'version': 'v2', 'user_id': '2288', 'session_id': 'f65f9d7f6049e857b5f77c5f45908f0adc68901a2c5b7d287e58e1861a23849e'})
                """
                redisClient.zadd(key, {entry['article_id']: 1}, incr=True)
                offset = id
                count = count + 1
            else:
                return count

    if generateLeaderboard() > 0:
        pipe = redisClient.pipeline(transaction=True)
        pipe.unlink('{popular_articles}')
        pipe.rename(key, '{popular_articles}')
        pipe.execute()


if __name__ == "__main__":
    """
    Example: docker exec rona_news_frontend_1 sh -c "python -u popular_articles_worker.py 300"

    The cli arg "300" represent 300 seconds ie. the period of article activity that
    should be considered for updating the data structure that holds the collection of
    popular articles.
    """
    if len(sys.argv) > 1:
        start = math.floor((datetime.now() - timedelta(seconds=int(sys.argv[1]))).timestamp() * 1000)
        run(start)
    else:
        run()
