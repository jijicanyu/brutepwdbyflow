#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
    proxy.py
    ~~~~~~~~
    
    HTTP Proxy Server in Python.
    
    :copyright: (c) 2013 by Abhinav Singh.
    :license: BSD, see LICENSE for more details.
"""
import os
import pdb
import queue
from time import sleep
from PyQt4 import QtCore

VERSION = (0, 2)
__version__ = '.'.join(map(str, VERSION[0:2]))
__description__ = 'HTTP Proxy Server in Python'
__author__ = 'Abhinav Singh'
__author_email__ = 'mailsforabhinav@gmail.com'
__homepage__ = 'https://github.com/abhinavsingh/proxy.py'
__license__ = 'BSD'

import sys
import multiprocessing
import datetime
import argparse
import logging
import socket
import select
import threading
logger = logging.getLogger(__name__)
# hdlr = logging.FileHandler("D:\\log.txt", "w+")
# logger.addHandler(hdlr)
# True if we are running on Python 3.
PY3 = sys.version_info[0] == 3

if PY3:
    text_type = str
    binary_type = bytes
    from urllib import parse as urlparse
else:
    text_type = unicode
    binary_type = str
    import urlparse


def text_(s, encoding='utf-8', errors='strict'):
    """ If ``s`` is an instance of ``binary_type``, return
    ``s.decode(encoding, errors)``, otherwise return ``s``"""
    if isinstance(s, binary_type):
        return s.decode(encoding, errors)
    return s  # pragma: no cover


def bytes_(s, encoding='utf-8', errors='strict'):
    """ If ``s`` is an instance of ``text_type``, return
    ``s.encode(encoding, errors)``, otherwise return ``s``"""
    if isinstance(s, text_type):  # pragma: no cover
        return s.encode(encoding, errors)
    return s

version = bytes_(__version__)

CRLF, COLON, SP = b'\r\n', b':', b' '

HTTP_REQUEST_PARSER = 1
HTTP_RESPONSE_PARSER = 2

HTTP_PARSER_STATE_INITIALIZED = 1
HTTP_PARSER_STATE_LINE_RCVD = 2
HTTP_PARSER_STATE_RCVING_HEADERS = 3
HTTP_PARSER_STATE_HEADERS_COMPLETE = 4
HTTP_PARSER_STATE_RCVING_BODY = 5
HTTP_PARSER_STATE_COMPLETE = 6

CHUNK_PARSER_STATE_WAITING_FOR_SIZE = 1
CHUNK_PARSER_STATE_WAITING_FOR_DATA = 2
CHUNK_PARSER_STATE_COMPLETE = 3
lock = threading.Lock()
Postdata = multiprocessing.Queue()

class ChunkParser(object):
    """HTTP chunked encoding response parser."""
    
    def __init__(self):
        self.state = CHUNK_PARSER_STATE_WAITING_FOR_SIZE
        self.body = b''
        self.chunk = b''
        self.size = None
    
    def parse(self, data):
        more = True if len(data) > 0 else False
        while more: more, data = self.process(data)
    
    def process(self, data):
        if self.state == CHUNK_PARSER_STATE_WAITING_FOR_SIZE:
            line, data = HttpParser.split(data)
            self.size = int(line, 16)
            self.state = CHUNK_PARSER_STATE_WAITING_FOR_DATA
        elif self.state == CHUNK_PARSER_STATE_WAITING_FOR_DATA:
            remaining = self.size - len(self.chunk)
            self.chunk += data[:remaining]
            data = data[remaining:]
            if len(self.chunk) == self.size:
                data = data[len(CRLF):]
                self.body += self.chunk
                if self.size == 0:
                    self.state = CHUNK_PARSER_STATE_COMPLETE
                else:
                    self.state = CHUNK_PARSER_STATE_WAITING_FOR_SIZE
                self.chunk = b''
                self.size = None
        return len(data) > 0, data

class HttpParser(object):
    """HTTP request/response parser."""
    
    def __init__(self, type=None):
        self.state = HTTP_PARSER_STATE_INITIALIZED
        self.type = type if type else HTTP_REQUEST_PARSER
        
        self.raw = b''
        self.buffer = b''
        
        self.headers = dict()
        self.body = None
        
        self.method = None
        self.url = None
        self.code = None
        self.reason = None
        self.version = None
        
        self.chunker = None
    
    def parse(self, data):
        self.raw += data
        data = self.buffer + data
        self.buffer = b''
        
        more = True if len(data) > 0 else False
        while more: 
            more, data = self.process(data)
        self.buffer = data
        return self.buffer

    def parse(self,data,method=b"GET"):
        # if method == b"POST":
        # print(data.decode('utf-8',errors='ignore'))
        self.raw += data
        data = self.buffer + data
        self.buffer = b''

        more = True if len(data) > 0 else False
        while more:
            more, data = self.process(data)
        self.buffer = data

    def process(self, data):
        if self.state >= HTTP_PARSER_STATE_HEADERS_COMPLETE and \
        (self.method == b"POST" or self.type == HTTP_RESPONSE_PARSER):
            if not self.body:
                self.body = b''

            if b'content-length' in self.headers:
                self.state = HTTP_PARSER_STATE_RCVING_BODY
                self.body += data
                if len(self.body) >= int(self.headers[b'content-length'][1]):
                    self.state = HTTP_PARSER_STATE_COMPLETE
            elif b'transfer-encoding' in self.headers and self.headers[b'transfer-encoding'][1].lower() == b'chunked':
                if not self.chunker:
                    self.chunker = ChunkParser()
                self.chunker.parse(data)
                if self.chunker.state == CHUNK_PARSER_STATE_COMPLETE:
                    self.body = self.chunker.body
                    self.state = HTTP_PARSER_STATE_COMPLETE
            
            return False, b''
        
        line, data = HttpParser.split(data)
        if line == False: return line, data
        
        if self.state < HTTP_PARSER_STATE_LINE_RCVD:
            self.process_line(line)
        elif self.state < HTTP_PARSER_STATE_HEADERS_COMPLETE:
            self.process_header(line)
        
        if self.state == HTTP_PARSER_STATE_HEADERS_COMPLETE and \
        self.type == HTTP_REQUEST_PARSER and \
        not self.method == b"POST" and \
        self.raw.endswith(CRLF*2):
            self.state = HTTP_PARSER_STATE_COMPLETE
        
        return len(data) > 0, data
    
    def process_line(self, data):
        line = data.split(SP)
        if self.type == HTTP_REQUEST_PARSER:
            self.method = line[0].upper()
            self.url = urlparse.urlsplit(line[1])
            self.version = line[2]
        else:
            self.version = line[0]
            self.code = line[1]
            self.reason = b' '.join(line[2:])
        self.state = HTTP_PARSER_STATE_LINE_RCVD
    
    def process_header(self, data):
        if len(data) == 0:
            if self.state == HTTP_PARSER_STATE_RCVING_HEADERS:
                self.state = HTTP_PARSER_STATE_HEADERS_COMPLETE
            elif self.state == HTTP_PARSER_STATE_LINE_RCVD:
                self.state = HTTP_PARSER_STATE_RCVING_HEADERS
        else:
            self.state = HTTP_PARSER_STATE_RCVING_HEADERS
            parts = data.split(COLON)
            key = parts[0].strip()
            value = COLON.join(parts[1:]).strip()
            self.headers[key.lower()] = (key, value)
    
    def build_url(self):
        if not self.url:
            return b'/None'
        
        url = self.url.path
        if url == b'': url = b'/'
        if not self.url.query == b'': url += b'?' + self.url.query
        if not self.url.fragment == b'': url += b'#' + self.url.fragment
        return url
    
    def build_header(self, k, v):
        return k + b": " + v + CRLF
    
    def build(self, del_headers=None, add_headers=None):
        req = b" ".join([self.method, self.build_url(), self.version])
        req += CRLF
        
        if not del_headers: del_headers = []
        for k in self.headers:
            if not k in del_headers:
                req += self.build_header(self.headers[k][0], self.headers[k][1])
        
        if not add_headers: add_headers = []
        for k in add_headers:
            req += self.build_header(k[0], k[1])
        
        req += CRLF
        if self.body:
            req += self.body
        
        return req
    
    @staticmethod
    def split(data):
        pos = data.find(CRLF)
        if pos == -1: return False, data
        line = data[:pos]
        data = data[pos+len(CRLF):]
        return line, data

class Connection(object):
    """TCP server/client connection abstraction."""
    
    def __init__(self, what):
        self.buffer = b''
        self.closed = False
        self.what = what # server or client
    
    def send(self, data):
        return self.conn.send(data)
    
    def recv(self, bytes=8192):
        try:
            data = self.conn.recv(bytes)
            if len(data) == 0:
                logger.debug('recvd 0 bytes from %s' % self.what)
                return None
            logger.debug('rcvd %d bytes from %s' % (len(data), self.what))
            return data
        except Exception as e:
            logger.exception('Exception while receiving from connection %s %r with reason %r' % (self.what, self.conn, e))
            return None
    
    def close(self):
        self.conn.close()
        self.closed = True
    
    def buffer_size(self):
        return len(self.buffer)
    
    def has_buffer(self):
        return self.buffer_size() > 0
    
    def queue(self, data):
        self.buffer += data
    
    def flush(self):
        sent = self.send(self.buffer)
        self.buffer = self.buffer[sent:]
        logger.debug('flushed %d bytes to %s' % (sent, self.what))

class Server(Connection):
    """Establish connection to destination server."""
    
    def __init__(self, host, port):
        super(Server, self).__init__(b'server')
        self.addr = (host, int(port))
    
    def connect(self):
        self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.conn.connect((self.addr[0], self.addr[1]))

class Client(Connection):
    """Accepted client connection."""
    
    def __init__(self, conn, addr):
        super(Client, self).__init__(b'client')
        self.conn = conn
        self.addr = addr

class ProxyError(Exception):
    pass

class ProxyConnectionFailed(ProxyError):
    
    def __init__(self, host, port, reason):
        self.host = host
        self.port = port
        self.reason = reason
    
    def __str__(self):
        return '<ProxyConnectionFailed - %s:%s - %s>' % (self.host, self.port, self.reason)

class Proxy(multiprocessing.Process):
    """HTTP proxy implementation.
    
    Accepts connection object and act as a proxy between client and server.
    """
    def __init__(self, client,callbackfun):
        super(Proxy, self).__init__()
        self.callbackfun = callbackfun
        self.start_time = self._now()
        self.last_activity = self.start_time
        
        self.client = client
        self.server = None
        
        self.request = HttpParser()
        self.response = HttpParser(HTTP_RESPONSE_PARSER)
        
        self.connection_established_pkt = CRLF.join([
            b'HTTP/1.1 200 Connection established',
            b'Proxy-agent: proxy.py v' + version,
            CRLF
        ])
    
    def _now(self):
        return datetime.datetime.utcnow()
    
    def _inactive_for(self):
        return (self._now() - self.last_activity).seconds
    
    def _is_inactive(self):
        return self._inactive_for() > 30
    
    def _process_request(self, data):
        # once we have connection to the server
        # we don't parse the http request packets
        # any further, instead just pipe incoming
        # data from client to server
        if self.server and not self.server.closed:
            self.server.queue(data)
            return
        
        # parse http request
        self.request.parse(data)
        #print('----------------')
        if self.request.method == b'POST':
            mydata = data.decode('utf-8',errors='ignore')
            #print(data.decode('utf-8',errors='ignore'))
            datas = mydata.split('\r\n\r\n')
            if len(datas) == 2 and len(datas[1].split('='))>2:
                file = open('postdata.txt','w+')
                file.write(mydata)
                file.close()

        #print('----------------')
        # once http request parser has reached the state complete
        # we attempt to establish connection to destination server
        if self.request.state == HTTP_PARSER_STATE_COMPLETE:
            logger.debug('request parser is in state complete')
            
            if self.request.method == b"CONNECT":
                host, port = self.request.url.path.split(COLON)
            elif self.request.url:
                host, port = self.request.url.hostname, self.request.url.port if self.request.url.port else 80
            
            self.server = Server(host, port)
            try:
                logger.debug('connecting to server %s:%s' % (host, port))
                self.server.connect()
                logger.debug('connected to server %s:%s' % (host, port))
            except Exception as e:
                self.server.closed = True
                raise ProxyConnectionFailed(host, port, repr(e))
            
            # for http connect methods (https requests)
            # queue appropriate response for client 
            # notifying about established connection
            if self.request.method == b"CONNECT":
                self.client.queue(self.connection_established_pkt)
            # for usual http requests, re-build request packet
            # and queue for the server with appropriate headers
            else:
                self.server.queue(self.request.build(
                    del_headers=[b'proxy-connection', b'connection', b'keep-alive'], 
                    add_headers=[(b'Connection', b'Close')]
                ))
    
    def _process_response(self, data):
        # parse incoming response packet
        # only for non-https requests
        if not self.request.method == b"CONNECT":
            # self.response.parse(data)
            self.response.parse(data)

        # queue data for client
        self.client.queue(data)

    def _access_log(self):
        host, port = self.server.addr if self.server else (None, None)
        if self.request.method == b"CONNECT":
            logger.info("%s:%s - %s %s:%s" % (self.client.addr[0], self.client.addr[1], self.request.method, host, port))
        elif self.request.method:
            logger.info("%s:%s - %s %s:%s%s - %s %s - %s bytes" % (self.client.addr[0], self.client.addr[1], self.request.method, host, port, self.request.build_url(), self.response.code, self.response.reason, len(self.response.raw)))
        
    def _get_waitable_lists(self):
        rlist, wlist, xlist = [self.client.conn], [], []
        logger.debug('*** watching client for read ready')
        
        if self.client.has_buffer():
            logger.debug('pending client buffer found, watching client for write ready')
            wlist.append(self.client.conn)
        
        if self.server and not self.server.closed:
            logger.debug('connection to server exists, watching server for read ready')
            rlist.append(self.server.conn)
        
        if self.server and not self.server.closed and self.server.has_buffer():
            logger.debug('connection to server exists and pending server buffer found, watching server for write ready')
            wlist.append(self.server.conn)
        
        return rlist, wlist, xlist
    
    def _process_wlist(self, w):
        if self.client.conn in w:
            logger.debug('client is ready for writes, flushing client buffer')
            self.client.flush()
        
        if self.server and not self.server.closed and self.server.conn in w:
            logger.debug('server is ready for writes, flushing server buffer')
            self.server.flush()
    
    def _process_rlist(self, r):
        if self.client.conn in r:
            logger.debug('client is ready for reads, reading')
            data = self.client.recv()
            self.last_activity = self._now()
            
            if not data:
                logger.debug('client closed connection, breaking')
                return True
            
            try:
                self._process_request(data)
            except ProxyConnectionFailed as e:
                logger.exception(e)
                self.client.queue(CRLF.join([
                    b'HTTP/1.1 502 Bad Gateway',
                    b'Proxy-agent: proxy.py v' + version,
                    b'Content-Length: 11',
                    b'Connection: close',
                    CRLF
                ]) + b'Bad Gateway')
                self.client.flush()
                return True
        
        if self.server and not self.server.closed and self.server.conn in r:
            logger.debug('server is ready for reads, reading')
            data = self.server.recv()
            self.last_activity = self._now()
            
            if not data:
                logger.debug('server closed connection')
                self.server.close()
            else:
                self._process_response(data)
        
        return False
    
    def _process(self):
        while True:
            rlist, wlist, xlist = self._get_waitable_lists()
            r, w, x = select.select(rlist, wlist, xlist, 1)
            
            self._process_wlist(w)
            if self._process_rlist(r):
                break
            
            if self.client.buffer_size() == 0:
                if self.response.state == HTTP_PARSER_STATE_COMPLETE:
                    logger.debug('client buffer is empty and response state is complete, breaking')
                    break
                
                if self._is_inactive():
                    logger.debug('client buffer is empty and maximum inactivity has reached, breaking')
                    break
    
    def run(self):
        logger.debug('Proxying connection %r at address %r' % (self.client.conn, self.client.addr))
        try:
            self._process()
        except KeyboardInterrupt:
            pass
        except Exception as e:
            logger.exception('Exception while handling connection %r with reason %r' % (self.client.conn, e))
        finally:
            logger.debug("closing client connection with pending client buffer size %d bytes" % self.client.buffer_size())
            self.client.close()
            if self.server:
                logger.debug("closed client connection with pending server buffer size %d bytes" % self.server.buffer_size())
            self._access_log()
            logger.debug('Closing proxy for connection %r at address %r' % (self.client.conn, self.client.addr))

class TCP(object):
    """TCP server implementation."""
    
    def __init__(self, callback,hostname='127.0.0.1', port=8899, backlog=100):
        self.callback = callback
        self.hostname = hostname
        self.port = port
        self.backlog = backlog
    
    def handle(self, client,callback):
        raise NotImplementedError()
    
    def run(self):
        try:
            logger.info('Starting server on port %d' % self.port)
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.hostname, self.port))
            self.socket.listen(self.backlog)
            while True:
                conn, addr = self.socket.accept()
                # logger.debug('Accepted connection %r at address %r' % (conn, addr))
                logger.info('Accepted connection %r at address %r' % (conn, addr))
                client = Client(conn, addr)
                self.handle(client,self.callback)
        except Exception as e:
            logger.exception('Exception while running the server %r' % e)
        finally:
            logger.info('Closing server socket')
            self.socket.close()

class HTTP():


    def __init__(self,callback,hostname='127.0.0.1', port=8899, backlog=100):
        self.callback = callback
        self.hostname = hostname
        self.port = port
        self.backlog = backlog

    def run(self):
        try:
            logger.info('Starting server on port %d' % self.port)
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.hostname, self.port))
            self.socket.listen(self.backlog)
            while True:
                conn, addr = self.socket.accept()
                # logger.debug('Accepted connection %r at address %r' % (conn, addr))
                logger.info('Accepted connection %r at address %r' % (conn, addr))
                client = Client(conn, addr)
                self.handle(client)
        except Exception as e:
            logger.exception('Exception while running the server %r' % e)
        finally:
            logger.info('Closing server socket')
            self.socket.close()



    def handle(self, client):
        proc = Proxy(client,self.getMydata)
        proc.daemon = True
        proc.start()
        logger.info('Started process %r to handle connection %r' % (proc, client.conn))

    def getMydata(self,data):
        self.callback(data)

class MyProxy(QtCore.QThread):
    def __init__(self):
        super(MyProxy, self).__init__()

    def run(self):
        self.start_server()


    def start_server(self,hostname = '127.0.0.1',port = 8899,backlog=100,hander=HTTP):
        try:
            proxy = hander(self.get_form_data,hostname,port,backlog)
            proxy.run()
        except KeyboardInterrupt:
            pass




    def get_form_data(self,data):
        #print('on get_form_data-------------------',data)
        pass


class MyProxy2(QtCore.QThread):

    updatedUI = QtCore.pyqtSignal(str)


    def __init__(self):
        super(MyProxy2, self).__init__()

    def run(self):
        while True:
            if os.path.exists('postdata.txt'):
                sleep(0.5)
                with open('postdata.txt','r') as file:
                    contents = file.readlines()

                data = [line for line in contents if line!='\n']
                # print('=============================')
                # print(data[len(data)-1])
                # print('===============================')
                data.insert(len(data)-1,'\n')
                postdata = ''.join(data)
                #print(postdata)
                self.updatedUI.emit(postdata)
                try:
                    os.remove('postdata.txt')
                except PermissionError:
                    sleep(2)
            else:
                sleep(0.5)

# if __name__ == '__main__':
    # main()
