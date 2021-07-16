import os
import sys
import redis
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv('REDIS_URL')

if REDIS_URL.startswith('rediss'):
    redisClient = redis.from_url(REDIS_URL, decode_responses=True, ssl_cert_reqs=None)
else:
    redisClient = redis.from_url(REDIS_URL, decode_responses=True)


def dropAndCreateSchema(force):
    """
    Optionally DROPs the two indices if they already exist
    """
    if force:
        try:
            redisClient.execute_command('FT.DROP articles')
        except redis.exceptions.ResponseError as e:
            print('Warning: Dropping index error (%s)' % e)

        try:
            redisClient.execute_command('FT.DROP analytics:search')
        except redis.exceptions.ResponseError as e:
            print('Warning: Dropping index error (%s)' % e)

    redisClient.execute_command("""
FT.CREATE articles ON HASH prefix 1 article: SCHEMA
docId TEXT NOSTEM
authors TAG
publishDate NUMERIC SORTABLE
title TEXT WEIGHT 5
blurb TEXT WEIGHT 2
body TEXT
url TEXT NOINDEX
""".replace('\n', ' '))

    redisClient.execute_command("""
FT.CREATE analytics:search ON HASH prefix 1 analytics:search: SCHEMA
docId TEXT NOSTEM
termOriginal TEXT SORTABLE
termNormalized TEXT SORTABLE
resultsTotal NUMERIC SORTABLE
ip TEXT SORTABLE
country TAG SORTABLE
platform TAG SORTABLE
version TAG SORTABLE
userId TEXT SORTABLE
sessionId TEXT SORTABLE
clicks NUMERIC SORTABLE
ts NUMERIC SORTABLE
""".replace('\n', ' '))


if __name__ == '__main__':
    """
    Example:
    python create-schema.py 1

    arg 1: drop schema if "1"
    """
    force = True if sys.argv[1] == '1' else False
    dropAndCreateSchema(force)
