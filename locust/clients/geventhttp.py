import time
import urllib

from locust import events
from locust.exception import CatchResponseError, ResponseError

from geventhttpclient import HTTPClient
from geventhttpclient.url import URL

class CookieJar(object):
    def __init__(self):
        self.cookies = {}

    def _extract(self, raw_data):
        parts = raw_data.split(";")
        name, value = parts[0].split("=")
        self.cookies[name] = value

    def check(self, headers):
        for key, value in headers:
            if "set-cookie" == key:
                self._extract(value)

    def get_cookies(self):
        cookie_data = ""
        for name, value in self.cookies.iteritems():
            cookie_data += "%s=%s;" % (name, value)

        return cookie_data


class HTTPError(Exception):
    """An HTTP error occurred."""
    response = None



def raise_for_status(self, allow_redirects=True):
    http_error_msg = ""

    if 300 <= self.status_code < 400 and self.status_code != 302:
        http_error_msg = '%s Redirection: %s' % (self.status_code, str(self))

    elif 400 <= self.status_code < 500:
        http_error_msg = '%s Client Error: %s' % (self.status_code, str(self))

    elif 500 <= self.status_code < 600:
        http_error_msg = '%s Server Error: %s' % (self.status_code, str(self))

    if http_error_msg:
        http_error = HTTPError(http_error_msg)
        http_error.response = self
        raise http_error

    return None

@property
def ok(self):
    try:
        self.raise_for_status()
    except Exception:
        return False
    return True

@property
def text(self):
    try:
        return self.content
    except Exception:
        self.content = self.read()
        return self.content


def patched_repr(self):
    return "<{klass} status={status}>".format(
        klass=self.__class__.__name__,
        status=self.status_code)


class GeventHttpSession(object):
    def __init__(self, base_url):
        self.base_url = base_url
        url = URL(self.base_url)
        #self.client = HTTPClient(url.host, url.port, version="HTTP/1.0")
        self.client = HTTPClient(url.host, url.port)
        self.cookie_jar = CookieJar()

    def post(self, url, data=None, **kwargs):
        return self.request('post', url, data=data, **kwargs)

    def get(self, url, **kwargs):
        return self.request('get', url, **kwargs)

    def request(self, method, url, name=None, catch_response=False, **kwargs):

        # store meta data that is used when reporting the request to locust's statistics
        request_meta = {"method": method,
                        "name": name or url}

        start_time = time.time()

        kwargs.setdefault("headers", {})

        if "data" in kwargs:
            kwargs["headers"]["Content-Type"] = "application/x-www-form-urlencoded"
            if isinstance(kwargs["data"], dict):
                kwargs["body"] = urllib.urlencode(kwargs["data"])
            else:
                kwargs["body"] = kwargs["data"]
            del kwargs["data"]

        if "allow_redirects" in kwargs:
            del kwargs["allow_redirects"]

        cookies = self.cookie_jar.get_cookies()
        if cookies:
            kwargs["headers"]["Cookie"] = cookies



        response = self.client.request(method, url, **kwargs)
        request_meta["response_time"] = int((time.time() - start_time) * 1000)
        request_meta["content_size"] = response.content_length

        self.cookie_jar.check(response.headers)

        if catch_response:
            response.locust_request_meta = request_meta
            return GeventHttpResponseContextManager(response)
        else:
            try:
                response.raise_for_status()
            except Exception, e:
                events.request_failure.fire(request_meta["method"], request_meta["name"], request_meta["response_time"], e, None)
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

        self.response = response
        self.status_code = response.status_code
        self.headers = dict(response.headers)

    def __enter__(self):
        return self

    @property
    def text(self):
        return self.response.text

    @property
    def ok(self):
        return self.response.ok

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
            try:
                self.response.raise_for_status()
            except HTTPError, e:
                self.failure(e)
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

from geventhttpclient.response import HTTPResponse
HTTPResponse.ok = ok
HTTPResponse.text = text
HTTPResponse.raise_for_status = raise_for_status
HTTPResponse.__repr__ = patched_repr
