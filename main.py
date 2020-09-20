import sys
import sensor
import lcd
import time

import usocket, network
from Maix import GPIO
from machine import UART
from fpioa_manager import fm, board_info


def get_wifi_credentials_from_camera_qr_code():
    clock = time.clock()
    lcd.init()
    sensor.reset()
    sensor.set_pixformat(sensor.RGB565)
    sensor.set_framesize(sensor.QVGA)
    sensor.set_vflip(1)
    sensor.run(1)
    sensor.skip_frames(30)

    while True:
        clock.tick()
        img = sensor.snapshot()
        res = img.find_qrcodes()
        fps = clock.fps()

        ssid = None
        password = None

        if len(res) > 0:
            data = res[0].payload().split(",", 1)
            if len(data) == 2:
                [ssid, password] = data
                img.draw_string(2,2, ssid, color=(0,128,0), scale=2)
                img.draw_string(2,50, password, color=(0,128,0), scale=2)

        lcd.display(img)

        if ssid is not None and password is not None:
            break

    return (ssid, password)


wifi_initialized = False
wifi_en = None

def connect_wifi(ssid, password):
    global wifi_initialized

    def init_wifi():
        global wifi_en
        fm.register(0, fm.fpioa.GPIOHS1, force=True)
        wifi_io0_en = GPIO(GPIO.GPIOHS1, GPIO.OUT)
        wifi_io0_en.value(0)

        # Enable ESP8285
        fm.register(8, fm.fpioa.GPIOHS0, force=True)
        wifi_en = GPIO(GPIO.GPIOHS0, GPIO.OUT)
        fm.register(board_info.WIFI_RX, fm.fpioa.UART2_TX, force=True)
        fm.register(board_info.WIFI_TX, fm.fpioa.UART2_RX, force=True)

    def wifi_enable(en):
        global wifi_en
        wifi_en.value(en)

    def wifi_reset():
        wifi_enable(0)
        time.sleep_ms(200)
        wifi_enable(1)
        time.sleep(2)
        uart = UART(UART.UART2, 115200, timeout=1000, read_buf_len=4096)
        tmp = uart.read()
        uart.write("AT+UART_CUR=921600,8,1,0,0\r\n")
        print(uart.read())
        # important! baudrate too low or read_buf_len too small will loose data
        uart = UART(UART.UART2, 921600, timeout=1000, read_buf_len=10240)
        uart.write("AT\r\n")
        tmp = uart.read()
        print(tmp)
        if not tmp.endswith("OK\r\n"):
            print("reset fail")
            return None
        try:
            nic = network.ESP8285(uart)
        except Exception:
            return None
        return nic

    if not wifi_initialized:
        init_wifi()
        wifi_initialized = True

    nic = wifi_reset()
    if not nic:
        raise Exception("WiFi init fail")

    nic.connect(ssid, password)
    nic.ifconfig()


class Response:
    def __init__(self, f):
        self.raw = f
        self.encoding = "utf-8"
        self._cached = None

    def close(self):
        if self.raw:
            self.raw.close()
            self.raw = None
        self._cached = None

    @property
    def content(self):
        if self._cached is None:
            try:
                self._cached = self.raw.read()
            finally:
                self.raw.close()
                self.raw = None
        return self._cached

    @property
    def text(self):
        return str(self.content, self.encoding)

    def json(self):
        import ujson
        return ujson.loads(self.content)


def request(method, url, data=None, json=None, headers={}, stream=None, parse_headers=True):
    redir_cnt = 1
    if json is not None:
        assert data is None
        import ujson
        data = ujson.dumps(json)

    while True:
        try:
            proto, dummy, host, path = url.split("/", 3)
        except ValueError:
            proto, dummy, host = url.split("/", 2)
            path = ""
        if proto == "http:":
            port = 80
        else:
            raise ValueError("Unsupported protocol: " + proto)

        if ":" in host:
            host, port = host.split(":", 1)
            port = int(port)

        ai = usocket.getaddrinfo(host, port, 0, usocket.SOCK_STREAM)
        ai = ai[0]

        resp_d = None
        if parse_headers is not False:
            resp_d = {}

        s = usocket.socket(ai[0], ai[1], ai[2])
        try:
            s.connect(ai[-1])
            s.write(b"%s /%s HTTP/1.0\r\n" % (method, path))
            if not "Host" in headers:
                s.write(b"Host: %s\r\n" % host)
            # Iterate over keys to avoid tuple alloc
            for k in headers:
                s.write(k)
                s.write(b": ")
                s.write(headers[k])
                s.write(b"\r\n")
            if json is not None:
                s.write(b"Content-Type: application/json\r\n")
            if data:
                s.write(b"Content-Length: %d\r\n" % len(data))
            s.write(b"Connection: close\r\n\r\n")
            if data:
                s.write(data)

            l = s.readline()
            #print(l)
            l = l.split(None, 2)
            status = int(l[1])
            reason = ""
            if len(l) > 2:
                reason = l[2].rstrip()
            while True:
                l = s.readline()
                if not l or l == b"\r\n":
                    break
                #print(l)

                if l.startswith(b"Transfer-Encoding:"):
                    if b"chunked" in l:
                        raise ValueError("Unsupported " + l)
                elif l.startswith(b"Location:") and 300 <= status <= 399:
                    if not redir_cnt:
                        raise ValueError("Too many redirects")
                    redir_cnt -= 1
                    url = l[9:].decode().strip()
                    #print("redir to:", url)
                    status = 300
                    break

                if parse_headers is False:
                    pass
                elif parse_headers is True:
                    l = l.decode()
                    k, v = l.split(":", 1)
                    resp_d[k] = v.strip()
                else:
                    parse_headers(l, resp_d)
        except OSError:
            s.close()
            raise

        if status != 300:
            break

    resp = Response(s)
    resp.status_code = status
    resp.reason = reason
    if resp_d is not None:
        resp.headers = resp_d
    return resp


def head(url, **kw):
    return request("HEAD", url, **kw)

def get(url, **kw):
    return request("GET", url, **kw)

def post(url, **kw):
    return request("POST", url, **kw)

def put(url, **kw):
    return request("PUT", url, **kw)

def patch(url, **kw):
    return request("PATCH", url, **kw)

def delete(url, **kw):
    return request("DELETE", url, **kw)


def main():
    ssid, password = get_wifi_credentials_from_camera_qr_code()
    connect_wifi(ssid, password)

    v = sys.implementation.version
    headers ={
        "User-Agent": "IntraCam/0.1 ({}/{}.{}.{})".format(sys.platform, v[0], v[1], v[2])
    }

    res = post("http://192.168.31.81:8080/ping", headers=headers)
    print("response:", res.status_code)
    content = res.content
    print(content)

    lcd.clear(lcd.RED)
    lcd.draw_string(120, 120, content, lcd.WHITE, lcd.RED)



if __name__ == "__main__":
    main()
