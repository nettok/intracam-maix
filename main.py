import sensor
import lcd
import time


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


def main():
    ssid, password = get_wifi_credentials_from_camera_qr_code()



if __name__ == "__main__":
    main()
