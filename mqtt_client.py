#!/usr/bin/python3
import json
import shlex
import socket
import subprocess
import time
import datetime

import paho.mqtt.client as mqtt
from gpiozero import LED
import RPi.GPIO as GPIO

MQTT_BROKER = '10.42.0.1'
successful_response_led = LED(13)       # Green led - successful response from server and shows if device power is on
is_device_running_led = LED(6)          # Blue led - device is running
waiting_for_server_reply_led = LED(19)  # Yellow led - waiting for server response
unsuccessful_response_led = LED(26)     # Red led - unsuccessful response from server


button_pin = 12
GPIO.setmode(GPIO.BCM)
GPIO.setup(button_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

registered = False

def turn_off_all_leds():
    """ Disable all leds """
    successful_response_led.off()
    is_device_running_led.off()
    waiting_for_server_reply_led.off()
    unsuccessful_response_led.off()

def delay(sec):
    start = datetime.datetime.now()
    while (datetime.datetime.now() - start) < datetime.timedelta(seconds=sec):
        pass

class DeviceMQTTClient(mqtt.Client):
    def __init__(self, device, priority, power, button_state=True, state=False, is_active=False, is_blocked=False,
                 is_consumer=1):
        super().__init__()
        self.button_state = button_state
        self.device = device
        self.priority = priority
        self.state = state
        self.is_active = is_active
        self.is_blocked = is_blocked
        self.is_consumer = is_consumer
        self.power = power
        self.set_request_topic = f"{socket.gethostname()}/set.to_server"
        self.set_reply_topic = f"{socket.gethostname()}/set.from_server"
        self.get_request_topic = f"{socket.gethostname()}/get.to_server"
        self.get_reply_topic = f"{socket.gethostname()}/get.from_server"

    def register_device(self):
        global device_state
        global registered
        device_state = "registration"
        unsuccessful_response_led.off()
        waiting_for_server_reply_led.on()
        self.state = False
        self.is_active = True
        payload = {"command": "register", "parameters": {"blocked": self.is_blocked, "priority": self.priority,
                                                         "state": self.state, "is_active": self.is_active}}
        print(f"MQTT Published: Topic = {self.set_request_topic}, payload = {payload}")
        self.publish(topic=self.set_request_topic, payload=json.dumps(payload))
        while not registered:
            delay(3)

    def power_on(self):
        global device_state
        device_state = "turning_on"
        unsuccessful_response_led.off()
        waiting_for_server_reply_led.on()
        power_on_payload = {"command": "power_on",
                            "parameters": {"blocked": self.is_blocked, "priority": self.priority,
                                           "state": True, "is_active": self.is_active
                                           }}
        print(f"MQTT Published: Topic = {self.set_request_topic}, payload = {power_on_payload}")
        self.publish(topic=self.set_request_topic, payload=json.dumps(power_on_payload))

    def power_off(self):
        global device_state
        device_state = "turning_off"
        unsuccessful_response_led.off()
        waiting_for_server_reply_led.on()
        power_on_payload = {"command": "power_off",
                            "parameters": {"blocked": self.is_blocked, "priority": self.priority,
                                           "state": False, "is_active": self.is_active
                                           }}
        print(f"MQTT Published: Topic = {self.set_request_topic}, payload = {power_on_payload}")
        self.publish(topic=self.set_request_topic, payload=json.dumps(power_on_payload))

    @staticmethod
    def on_publish(client, userdata, result):
        print("MQTT callback: Published message")

    @staticmethod
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            print("MQTT callback: Client connected to MQTT broker")
        else:
            print("MQTT callback: Bad connection Returned code=", rc)

    @staticmethod
    def on_message(client, userdata, msg):
        """
        message parameter is a message class with members topic, qos, payload, retain.
        """
        global device_state
        global registered
        print(f"MQTT callback: Recieved message on topic = {msg.topic}, qos = {msg.qos}, payload = {str(msg.payload)}")
        if msg.retain == 1 and client.skip_retained:
            print("MQTT. Skip retained msg: " + msg.topic + " " + str(msg.qos) + " " + str(msg.payload))
        else:
            try:
                client.last = json.loads(msg.payload.decode('utf-8'))
            except ValueError:
                client.last = msg.payload.decode('utf-8')

            if msg.topic == client.set_reply_topic:  # TODO wrap changing parameters and reply to server into function
                if "result" in client.last.keys():
                    if client.last.get("result"):
                        waiting_for_server_reply_led.off()
                        if device_state == "registration":
                            registered = True
                        successful_response_led.on()
                        if device_state != "turning_on":
                            time.sleep(1)
                            successful_response_led.off()
                        if client.last.get("parameters"):
                            params = client.last.get("parameters")
                            if "is_active" in params.keys():
                                client.is_active = params["is_active"]
                                print(f"Changed parameter 'is_active' value to {params['is_active']}")
                                payload = {"result": True, "parameters": {"is_active": params['is_active']}}
                                print(f"MQTT Published: Topic = {client.set_request_topic}, payload = {payload}")
                                client.publish(client.set_request_topic, json.dumps(payload))
                            if "state" in params.keys():
                                client.state = params["state"]
                                print(f"Changed parameter 'state' value to {params['state']}")
                                payload = {"result": True, "parameters": {"state": params['state']}}
                                print(f"MQTT Published: Topic = {client.set_request_topic}, payload = {payload}")
                                client.publish(client.set_request_topic, json.dumps(payload))
                            if "priority" in params.keys():
                                client.priority = params["priority"]
                                print(f"Changed parameter 'priority' value to {params['priority']}")
                                payload = {"result": True, "parameters": {"priority": params['priority']}}
                                print(f"MQTT Published: Topic = {client.set_request_topic}, payload = {payload}")
                                client.publish(client.set_request_topic, json.dumps(payload))
                            if "blocked" in params.keys():
                                client.is_blocked = params["blocked"]
                                print(f"Changed parameter 'blocked' value to {params['blocked']}")
                                if client.is_blocked:
                                    successful_response_led.off()
                                    client.power_off()
                    elif not client.last.get("result"):
                        waiting_for_server_reply_led.off()
                        print("Request rejected")
                        unsuccessful_response_led.on()
                        #if device_state == "registration":
                        client.register_device()
                elif "command" in client.last.keys():
                    if client.last.get("command") == "power_off":
                        successful_response_led.off()
                        client.state = False
                        print(f"Changed parameter 'state' to {client.state}")
                        payload = {"result": True, "parameters": {"state": False}}
                        print(f"MQTT Published: Topic = {client.set_request_topic}, payload = {payload}")
                        client.publish(client.set_request_topic, json.dumps(payload))
                    elif client.last.get("command") == "power_on":
                        successful_response_led.on()
                        client.state = True
                        print(f"Changed parameter 'state' to {client.state}")
                        payload = {"result": True, "parameters": {"state": True}}
                        print(f"MQTT Published: Topic = {client.set_request_topic}, payload = {payload}")
                        client.publish(client.set_request_topic, json.dumps(payload))

    def button_callback(self, button_pin):
        """ Handle pressing power button on 'button_pin' """
        print("Button was pressed!")
        if not self.is_blocked:
            if successful_response_led.is_lit:
                self.power_off()
            else:
                self.power_on()
            #delay(1)
        else:
            print("Device is blocked.")


def main_client_loop():
    turn_off_all_leds()
    with open('/home/pi/mqtt_client/config/config.json') as config:
        data = json.load(config)

    if socket.gethostname() in data.keys():
        params = data[socket.gethostname()]
    else:
        raise NameError("Config doesn't have data for your hostname")
    client = DeviceMQTTClient(device=params['device'], priority=params['priority'], is_consumer=params['is_consumer'],
                              power=params['power'])
    client.connect(MQTT_BROKER)
    client.loop_start()
    is_device_running_led.on()
    GPIO.add_event_detect(button_pin, GPIO.FALLING, callback=client.button_callback, bouncetime=400)
    if not client.is_consumer:  # Non-consumers supply energy. For them state and is_active by default True
        client.state = True
        client.is_active = True

    client_args = {"device": client.device, "power": client.power, "is_consumer": client.is_consumer}
    command = f"avahi-publish -s {socket.gethostname()} _mqtt._tcp 1883 '{json.dumps(client_args)}'"
    process = subprocess.Popen(shlex.split(command))  # publish avahi service
    print(f"Executed command: {command}\nSubprocess info. ID: {process.pid} Output: {process.stdout}"
          f" Error = {process.stderr}")

    # subscribe on topics
    client.subscribe(client.set_reply_topic)
    client.subscribe(client.get_reply_topic)
    time.sleep(5)  # Time for avahi to resolve faster than mqtt
    client.register_device()
    print("Device registered")

    try:
        print("To quit press Ctrl+C ")
        process.wait()
    except KeyboardInterrupt:
        try:
            process.terminate()
            client.loop_stop()
        except OSError:
            print("OSE Error raised")
            pass
        process.wait()


main_client_loop()
