import time
import urllib

from locust import events
from locust.exception import CatchResponseError, ResponseError

from geventhttpclient import HTTPClient
from geventhttpclient.url import URL
import Cookie

class CookieJar(object):
    def __init__(self):
        self.cookies = []

    def check(self, headers):
        for key, value in headers:
            if "set-cookie" == key:
                s = Cookie.SimpleCookie(value)


class GeventHttpSession(object):
    def __init__(self, base_url):
        self.base_url = base_url
        url = URL(self.base_url)
        self.client = HTTPClient(url.host, url.port, version="HTTP/1.0")
        #self.cookie_jar = CookieJar()

    def post(self, url, data=None, **kwargs):
        return self.request('post', url, data=data, **kwargs)

    def get(self, url, **kwargs):
        return self.request('get', url, **kwargs)

    def request(self, method, url, name=None, catch_response=False, **kwargs):

        # store meta data that is used when reporting the request to locust's statistics
        request_meta = {"method": method,
                        "name": name or url}

        start_time = time.time()

        if "data" in kwargs:
            kwargs.setdefault("headers", {})
            kwargs["headers"]["Content-Type"] =  "application/x-www-form-urlencoded"
            kwargs["body"] = urllib.urlencode(kwargs["data"])
            del kwargs["data"]

        if "allow_redirects" in kwargs:
            del kwargs["allow_redirects"]


        response = self.client.request(method, url, **kwargs)
        request_meta["response_time"] = int((time.time() - start_time) * 1000)
        request_meta["content_size"] = response.content_length

        #self.cookie_jar.check(response.headers)

        if catch_response:
            response.locust_request_meta = request_meta
            return GeventHttpResponseContextManager(response)
        else:
            if response.status_code != 200:
                events.request_failure.fire(request_meta["method"], request_meta["name"], request_meta["response_time"], "Error", None)
            else:
                events.request_success.fire(
                    request_meta["method"],
                    request_meta["name"],
                    request_meta["response_time"],
                    request_meta["content_size"],
                )
            return response

class GeventHttpResponseContextManager(object):
    _is_reported = False

    def __init__(self, response):
        # copy data from response to this object
        self.__dict__ = response.__dict__

        self.status_code = response.status_code
        self.headers = dict(response.headers)

    def __enter__(self):
        return self

    def __exit__(self, exc, value, traceback):
        if self._is_reported:
            # if the user has already manually marked this response as failure or success
            # we can ignore the default haviour of letting the response code determine the outcome
            return exc is None

        if exc:
            if isinstance(value, ResponseError):
                self.failure(value)
            else:
                return False
        else:
            if self.status_code != 200:
                self.failure("Status code was %d" % (self.status_code,))
            else:
                self.success()
        return True

    def success(self):
        """
        Report the response as successful

        Example::

            with self.client.get("/does/not/exist", catch_response=True) as response:
                if response.status_code == 404:
                    response.success()
        """
        events.request_success.fire(
            self.locust_request_meta["method"],
            self.locust_request_meta["name"],
            self.locust_request_meta["response_time"],
            self.locust_request_meta["content_size"],
        )
        self._is_reported = True

    def failure(self, exc):
        """
        Report the response as a failure.

        exc can be either a python exception, or a string in which case it will
        be wrapped inside a CatchResponseError.

        Example::

            with self.client.get("/", catch_response=True) as response:
                if response.content == "":
                    response.failure("No data")
        """
        if isinstance(exc, basestring):
            exc = CatchResponseError(exc)

        events.request_failure.fire(
            self.locust_request_meta["method"],
            self.locust_request_meta["name"],
            self.locust_request_meta["response_time"],
            exc,
            self,
        )
        self._is_reported = True