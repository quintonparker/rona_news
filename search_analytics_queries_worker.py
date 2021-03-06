import redis
import os
import sys
from redisearch import Client
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv('REDIS_URL')

if REDIS_URL.startswith('rediss'):
    redisClient = redis.from_url(REDIS_URL, decode_responses=True,
                                 ssl_cert_reqs=None)
else:
    redisClient = redis.from_url(REDIS_URL, decode_responses=True)

redisearchClient = Client('analytics:search', conn=redisClient)


def run(consumer, group='search_analytics', stream='events:search:queries'):
    """
    Subscribe to queries events and update the analytics search index
    """
    print(f'Starting {group}/{consumer} consumer listen on {stream}')
    try:
        redisClient.xgroup_create(stream, group, id='0', mkstream=True)
    except redis.exceptions.ResponseError as error:
        print(error)
        if not str(error) == 'BUSYGROUP Consumer Group name already exists':
            raise error

    """
    Sample (id,entry) tuple

    ('1589288437521-0', {'_version': 'v1', 'query': '@title|blurb|body:teachers ', 'term_original': 'teachers', 'term_normalized': 'teachers', 'results_total': '309', 'ip': '172.25.0.1', 'user_id': '', 'session_id': 'bb1ee16a3eb745be8d9fcf71d55c3a80'})
    """
    while True:
        for offset in ['0', '>']:
            for _, entries in redisClient.xreadgroup(
                    group, consumer, {stream: offset}, block=0):
                for id, entry in entries:
                    print((id, entry))
                    doc = {}
                    docId = ('query:%s' % id)
                    doc['termOriginal'] = entry['term_original']
                    doc['termNormalized'] = entry['term_normalized']
                    doc['resultsTotal'] = entry['results_total']
                    doc['ip'] = entry['ip']
                    doc['userId'] = entry['user_id']
                    doc['sessionId'] = entry['session_id']
                    doc['clicks'] = 0
                    doc['ts'] = id.split('-', maxsplit=1)[0]
                    print((docId, doc))
                    redisearchClient.add_document(
                        docId,
                        replace=True,
                        partial=True,
                        # nosave=True,
                        **doc)
                    redisClient.xack(stream, group, id)


if __name__ == "__main__":
    """
    Example: python search_analytics_queries_worker.py consumer1
    """
    run(sys.argv[1])
