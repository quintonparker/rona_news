# Rona News

This is a mock/poc mobile web app for a searchable news database written in Python using the Flask framework

In this POC we show that Redisearch is not just a viable search engine but also that the Redis ecosystem proves to be a useful platform for building a rich, interactive, observable, and realtime system of engagement

## Install & Run

```
docker-compose up
```

Visit http://localhost:5000 to perform searches and http://localhost:5000/analytics for the analytics dashboard

Example `docker ps` output

```
CONTAINER ID        IMAGE                         COMMAND                  CREATED             STATUS              PORTS                    NAMES
05a865c8fc78        rona_news:latest              "flask run --host=0.…"   26 minutes ago      Up 23 minutes       0.0.0.0:5000->5000/tcp   rona_news_frontend_1
8f007ecb1626        rona_news:latest              "python -u search_an…"   26 minutes ago      Up 6 minutes                                 rona_news_analytics_queries_worker_1
a4da04ba3806        rona_news:latest              "python -u recently_…"   26 minutes ago      Up 23 minutes                                rona_news_recently_viewed_worker_1
cf991a0897dd        rona_news:latest              "python -u search_an…"   26 minutes ago      Up 23 minutes                                rona_news_analytics_clicks_worker_1
2eb7eccc1ce9        redislabs/redisearch:latest   "docker-entrypoint.s…"   26 minutes ago      Up 23 minutes       0.0.0.0:6379->6379/tcp   rona_news_redisearch_1
```

## How does this work?

`app.py` is the main entrypoint for the web app. It is a long running process that exposes a web app at `http://localhost:5000`. Its stateless and therefore can be scaled horizontally.

### Redis

A single instance of [Redis OSS](http://redis.io/) with the [Redisearch OSS](https://redisearch.io/) module enabled is provisioned for the application.

The Redis instance can also be inspected and queried external to the app via `redis-cli` or a GUI tool such as [RedisInsight](https://redislabs.com/redisinsight/) using ip/port combo `localhost:6379`.

Note: For the purposes of the POC, Redis OSS is adequate and the functionality used here is backwards-compatible with [Redisearch Enterprise](https://redislabs.com/redis-enterprise/technology/redis-search/).

### Bootstrapping the database

* `create-schema.py` is a cli script that connects to a Redisearch database and creates the `articles` and `analytics:search` search indices
* `press-release-indexer.py` is a cli script that parses `sbg_article_202003311020.txt` and imports the articles into a Redisearch search index called `articles`
* `help-guide-indexer.py` is a cli script that parses `smartphoneApp.json` and imports the help guides into a Redisearch search index called `articles`
* `reimport.sh` glues this all together and simulates article import by country, platform, and version

### Background/Async workers

* `recently_viewed_worker.py` subscribes to article view events ([via Redis Streams](https://redis.io/topics/streams-intro)) in realtime and builds unique index of recently viewed articles per user session. Can be scaled horizontally
* `search_analytics_clicks_worker.py` and `search_analytics_queries_worker.py` are long-running scripts that subscribe to search events ([via Redis Streams](https://redis.io/topics/streams-intro)) and updates the `analytics:search` search index. Can be scaled horizontally

### Popular Articles

Popular articles worker is intended to be a short-lived scheduled process that is invoked every X seconds/minutes/hours so as to rebuild the list of popular articles that powers the Popular Articles UI Widget

```
docker exec rona_news_frontend_1 sh -c "python -u popular_articles_worker.py 300"
```
The cli arg "300" represent 300 seconds. The period of article activity that should be considered for updating the data structure that holds the collection of popular articles.