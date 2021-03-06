#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import logging
import traceback

from toolz import merge
from executor import Executor

from utils import IterableError


__author__ = 'tong'

logger = logging.getLogger('stream.logger')


class Output(Executor):
    def handle(self, item):
        try:
            self.output(item)
        except Exception, e:
            logger.error('OUTPUT %s %s error: %s' % (self.__class__.__name__, self.name, e))
            return {'data': item, 'exception': e, 'traceback': traceback.format_exc()}

    def output(self, item):
        pass

    def outputmany(self, items):
        for item in items:
            self.output(item)


class Kafka(Output):
    def __init__(self, topic, server, client=None, name=None, ignore_exc=None, **kwargs):
        try:
            import kafka
        except ImportError:
            raise Exception('Lack of kafka module, try to execute `pip install kafka-python>=1.3.1` install it')

        client = client or kafka.SimpleClient
        self._producer = None
        self._topic = topic
        try:
            self._kafka = client(server, **kwargs)
        except Exception, e:
            raise Exception('kafka client init failed: %s' % e)
        self.producer(kafka.SimpleProducer)
        super(Kafka, self).__init__(name, ignore_exc)

    def producer(self, producer, **kwargs):
        try:
            self._producer = producer(self._kafka, **kwargs)
        except Exception, e:
            raise Exception('kafka producer init failed: %s' % e)

    def output(self, item):
        if not self._producer:
            raise Exception('No producer init')
        logger.info('OUTPUT INSERT Kafka 1: %s' % self._producer.send_messages(self._topic, item))

    def outputmany(self, items):
        if not self._producer:
            raise Exception('No producer init')
        logger.info('OUTPUT INSERT Kafka %s: %s' % (len(items), self._producer.send_messages(self._topic, *items)))

    def close(self):
        if self._producer:
            del self._producer
            self._producer = None


class HTTPRequest(Output):
    def __init__(self, server, headers=None, method='GET', request_args=None, timeout=None,
                 catch_exc=None, **kwargs):
        from .. import __version__
        self.server = server
        self.method = method.upper()
        self.headers = headers or {}
        self.timeout = timeout
        self.request_args = request_args or {}
        self.catch_exc = catch_exc or (lambda x: not bool(x))
        self.headers.setdefault('User-Agent', 'python-stream %s HTTPRequest' % __version__)
        super(HTTPRequest, self).__init__(**kwargs)

    def output(self, item):
        import requests
        timeout = (self.timeout, self.timeout) if self.timeout else None
        ret = requests.request(self.method, self.server, headers=self.headers,
                               timeout=timeout, **merge(self.arguments(item), self.request_args))
        if self.catch_exc(ret):
            raise Exception(ret)
        logger.info('OUTPUT INSERT Request 1: %s' % ret)

    def outputmany(self, items):
        import grequests
        tasks = [grequests.request(
            self.method, self.server, headers=self.headers, **self.arguments(item)
        ) for item in items]
        ret = grequests.map(tasks, gtimeout=self.timeout)
        if not any([self.catch_exc(_) for _ in ret]):
            logger.info('OUTPUT INSERT Request %s' % len(ret))
            return
        errors = []
        for i, _ in enumerate(ret):
            if _ is None:
                errors.append({'data': items[i], 'exception': tasks[i].exception, 'traceback': tasks[i].traceback})
            elif self.catch_exc(_):
                errors.append({'data': items[i], 'exception': Exception(_), 'traceback': None})
        raise IterableError(*errors)

    def arguments(self, item):
        if self.method == 'GET':
            return {'params': item}
        if self.method == 'POST':
            return {'data': self.data(item)}

    def data(self, data):
        ctype = self.headers.get('Content-Type')
        if ctype == 'application/json':
            return json.dumps(data, separators=(',', ':'))
        return data


class File(Output):
    def __init__(self, filename, **kwargs):
        self.filename = filename
        self.stream = open(self.filename, 'a')
        super(File, self).__init__(**kwargs)

    def __del__(self):
        self.stream.close()

    def output(self, item):
        self.stream.write(item+'\n')
        self.stream.flush()

    def outputmany(self, items):
        self.stream.writelines('\n'.join(items)+'\n')
        self.stream.flush()


class Csv(File):
    def __init__(self, filename, name=None, ignore_exc=True, **kwargs):
        import csv
        super(Csv, self).__init__(filename, name=name, ignore_exc=ignore_exc, **kwargs)
        self.writer = csv.writer(self.stream, **kwargs)

    def output(self, item):
        self.writer.writerow(item)

    def outputmany(self, items):
        self.writer.writerows(items)


class Screen(Output):
    def output(self, item):
        print item

    def outputmany(self, items):
        print '\n'.join(items)+'\n'


Stdout = Screen


class Null(Output):
    pass
