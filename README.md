# Home Assistant NFC Reader

Like [adonno's](https://github.com/adonno/tagreader) tagreader component, but with a USB NFC reader that you can plug into a PC or Raspberry Pi.

You can use it to build a similar [NFC Jukebox with Home Assistant](https://www.home-assistant.io/integrations/tag/) but without having to solder or 3D print anything 😁.

**UPDATE:** It turns out this does not work on Debian Trixie (because it ships with a newer version of `pcscd`). If using a Raspberry Pi with Docker, the container now bundles its own `pcscd` so the host OS version doesn't matter anymore. See [Docker](#docker) below for the updated setup.

## Background

I created an NFC Jukebox with Home Assistant using [adonno's](https://github.com/adonno/tagreader) tagreader component, but unfortunately it broke 😢.
When I tried to purchase a replacement, I found that lead times were around 1 month and my wife (who had gotten to really like the jukebox) did not want to wait that long.

So I decided to see if I can use a USB NFC reader (that Amazon could ship me in like 4 hours) instead.
Turns out getting the code working took a lot longer than that (due to a bug in libNFC, among other things), but I figured I may as well share it in case it's useful to anyone else.

## Requirements

I've tested this with

- This particular [ACR122U NFC reader](https://www.amazon.com/dp/B07DK9GX1N)
- These specific [NTAG215 NFC tags](https://www.amazon.com/dp/B0CHVWTRGC).

It might work with other NFC readers/tags, but I have no plans on using anything else.

## Installation

The Docker container now bundles `pcscd` internally and talks to the USB reader directly, so you no longer need PC/SC installed on the host. You just need to make sure nothing else on the host is trying to claim the reader.

### Host Setup

If you previously had `pcscd` running on the host, disable it so it doesn't fight with the one in the container:

```bash
sudo systemctl stop pcscd pcscd.socket
sudo systemctl disable pcscd pcscd.socket
```

You also need to blacklist the kernel NFC modules. Linux will try to claim the ACR122U's NFC chip via `pn533_usb`, which prevents `pcscd` from accessing it:

```bash
echo -e "blacklist pn533_usb\nblacklist pn533\nblacklist nfc" | sudo tee /etc/modprobe.d/blacklist-nfc.conf
sudo rmmod pn533_usb pn533 nfc 2>/dev/null  # unload immediately if loaded
```

You can verify the reader is available with `lsusb` — you should see something like `072f:2200 Advanced Card Systems, Ltd ACR122U`.

### Home Assistant

You need to have the MQTT integration enabled and configured in Home Assistant. The [official documentation](https://www.home-assistant.io/integrations/mqtt/) describes that in detail, but you can also try clicking this giant button:

[![Add integration to MY Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start?domain=mqtt)

### Docker

The container needs privileged access to the USB bus so `pcscd` can talk to the reader.
An example [docker-compose.yml](./docker-compose.yml) file is included in this repository. Here it is for reference:

```yaml
services:
  nfc-reader:
    image: ghcr.io/shocklateboy92/homeassistant-usb-tagreader:main
    container_name: nfc-reader
    privileged: true
    volumes:
      - /dev/bus/usb:/dev/bus/usb # USB device passthrough
    restart: unless-stopped
    environment:
      - LOG_LEVEL=INFO # Set log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
      # MQTT configuration
      - MQTT_BROKER=your-mqtt-broker
      - MQTT_USERNAME=your-username
      - MQTT_PASSWORD=your-password
```

The container will start `pcscd` automatically on boot.

`your-mqtt-broker` is usually your home assistant instance, which is typically `homeassistant.local`. If you use a non-standard port, you can specify an `MQTT_PORT` environment variable as well. You can see the full list of environment variables in the top of [mqtt_handler.py](./mqtt_handler.py).

`your-username` and `your-password` are the credentials you use to connect to your MQTT broker. If you clicked the giant button above and had the Home Assistant MQTT integration install and configure the MQTT Add-on for you, the usernames and passwords that you use to log into Home Assistant will also work for the MQTT broker.

You can use your regular user if you'd like, but [their documentation](https://github.com/home-assistant/addons/blob/5c01a323ba84e6aa534302ace0b7539d3582e65d/mosquitto/DOCS.md#how-to-use) recommends creating a dedicated user for MQTT.

## Usage

Since this uses MQTT, it can't fire the `tag_scanned` event like adonno's tagreader component does.

Instead, it creates a sensor that contains the Tag ID of the currently present NFC tag.<br>
I.e. if there's a tag on top of the NFC reader right now the sensor state will be ID of that tag, and once you remove the tag the sensor state will be `unknown`.

![NFC Reader Current Tag sensor](./sensor-screenshot.png)

You can use this sensor in automation triggers to play the approriate music then its state changes.

# Support

I don't think I'll have much time to investigate issues or add new features, but I will try to at least take a look at pull requests if you've figured out how to fix something.

Create the PR of the earliest rough draft that you can, so I can give feedback on whether I like your approach before you spend a significant amount of time on it.

## AI Use disclosure

Claude Sonnet 4 wrote a significant portion of this code. I did read its output and guide it to bring the code up to my standards. However, if you have any philosophical objections to AI-generated code, you don't have to use this project 😉.
