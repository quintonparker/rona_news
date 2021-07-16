import sys
import ast
import json
import csv
import os
import redis
from datetime import datetime
from redisearch import Client
from dotenv import load_dotenv

load_dotenv()

REDIS_URL = os.getenv('REDIS_URL')

if REDIS_URL.startswith('rediss'):
    redisClient = redis.from_url(REDIS_URL, decode_responses=True, ssl_cert_reqs=None)
else:
    redisClient = redis.from_url(REDIS_URL, decode_responses=True)


def parsePublishDate(d):
    """
    Parses 2020-03-31 12:55 date formats
    """
    return datetime.strptime(d, '%Y-%m-%d %H:%M')


def run(file, index):
    """
    Read csv file line by line & add_document to index using redisearch-py BatchIndexer
    """
    with open(file) as csvFile:
        articleReader = csv.DictReader(csvFile, delimiter=',', quotechar='"', strict=True)
        counter = 0
        pipe = redisClient.pipeline()
        for article in articleReader:
            print(json.dumps(article))
            docId = article['id']

            """
            docId TEXT NOSTEM
            authors TAG
            publishDate NUMERIC
            title TEXT WEIGHT 5
            blurb TEXT WEIGHT 2
            body TEXT
            url TEXT NOINDEX
            """
            doc = {}
            doc['authors'] = ",".join(ast.literal_eval(article['authors']))
            doc['publishDate'] = int(parsePublishDate(article['publish_date']).timestamp())
            doc['title'] = article['title']
            doc['blurb'] = article['description']
            doc['body'] = article['text']
            doc['url'] = article['url']
            print((docId, json.dumps(doc)))
            pipe.hset(f'article:{docId}', mapping=doc)
            counter = counter + 1

            if counter % 500:
                print(pipe.execute())
                counter = 0
                pipe = redisClient.pipeline()
        pipe.execute()


if __name__ == '__main__':
    """
    Example: python indexer.py news.csv

    arg 1: feed file path to process
    arg 2: name of search index
    """

    run(sys.argv[1], sys.argv[2])
