### BEGIN LICENSE
# Copyright (c) 2015 Andrzej Taramina <andrzej@chaeron.com>

# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation
# files (the "Software"), to deal in the Software without
# restriction, including without limitation the rights to use,
# copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following
# conditions:

# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
# OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
# HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.
### END LICENSE

##############################################################################
#                                                                            #
#       Core Imports                                                         #
#                                                                            #
##############################################################################

import threading
import math
import os, os.path, sys
import time
import datetime
import urllib2
import json
import random
import socket
import re


##############################################################################
#                                                                            #
#       Kivy UI Imports                                                      #
#                                                                            #
##############################################################################

import kivy
kivy.require( '1.9.0' ) # replace with your current kivy version !

from kivy.app import App
from kivy.uix.button import Button
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.label import Label
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.slider import Slider
from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.storage.jsonstore import JsonStore
from kivy.uix.screenmanager import ScreenManager, Screen, NoTransition


##############################################################################
#                                                                            #
#       Other Imports                                                        #
#                                                                            #
##############################################################################

import cherrypy
import schedule


##############################################################################
#                                                                            #
#       GPIO & Simulation Imports                                            #
#                                                                            #
##############################################################################

try:
	import RPi.GPIO as GPIO
except ImportError:
	import FakeRPi.GPIO as GPIO


##############################################################################
#                                                                            #
#       Sensor Imports                                                       #
#                                                                            #
##############################################################################

from w1thermsensor import W1ThermSensor


##############################################################################
#                                                                            #
#       MQTT Imports (used for logging and/or external sensors)              #
#                                                                            #
##############################################################################

try:
	import paho.mqtt.client as mqtt
	import paho.mqtt.publish as publish
	mqttAvailable = True
except ImportError:
	mqttAvailable = False


##############################################################################
#                                                                            #
#       Utility classes                                                      #
#                                                                            #
##############################################################################

class switch(object):
    def __init__(self, value):
        self.value = value
        self.fall = False

    def __iter__(self):
        """Return the match method once, then stop"""
        yield self.match
        raise StopIteration
    
    def match(self, *args):
        """Indicate whether or not to enter a case suite"""
        if self.fall or not args:
            return True
        elif self.value in args: # changed for v1.5, see below
            self.fall = True
            return True
        else:
            return False


##############################################################################
#                                                                            #
#       MySensor.org Controller compatible translated constants              #
#                                                                            #
##############################################################################

MSG_TYPE_SET 						= "set"
MSG_TYPE_PRESENTATION 				= "presentation"

CHILD_DEVICE_NODE					= "node"
CHILD_DEVICE_MQTT					= "mqtt"
CHILD_DEVICE_UICONTROL_HEAT			= "heatControl"
CHILD_DEVICE_UICONTROL_COOL			= "coolControl"
CHILD_DEVICE_UICONTROL_FAN			= "fanControl"
CHILD_DEVICE_UICONTROL_HOLD			= "holdControl"
CHILD_DEVICE_UICONTROL_SLIDER		= "tempSlider"
CHILD_DEVICE_WEATHER_CURR			= "weatherCurrent"
CHILD_DEVICE_WEATHER_FCAST_TODAY	= "weatherForecastToday"
CHILD_DEVICE_WEATHER_FCAST_TOMO		= "weatherForecastTomorrow"
CHILD_DEVICE_HEAT					= "heat"
CHILD_DEVICE_COOL					= "cool"
CHILD_DEVICE_FAN					= "fan"
CHILD_DEVICE_PIR					= "motionSensor"
CHILD_DEVICE_TEMP					= "temperatureSensor"
CHILD_DEVICE_SCREEN					= "screen"
CHILD_DEVICE_SCHEDULER				= "scheduler"
CHILD_DEVICE_WEBSERVER				= "webserver"

CHILD_DEVICES						= [
	CHILD_DEVICE_NODE,
	CHILD_DEVICE_MQTT,
	CHILD_DEVICE_UICONTROL_HEAT,
	CHILD_DEVICE_UICONTROL_COOL,
	CHILD_DEVICE_UICONTROL_FAN,
	CHILD_DEVICE_UICONTROL_HOLD,
	CHILD_DEVICE_UICONTROL_SLIDER,
	CHILD_DEVICE_WEATHER_CURR,
	CHILD_DEVICE_WEATHER_FCAST_TODAY,
	CHILD_DEVICE_WEATHER_FCAST_TOMO,
	CHILD_DEVICE_HEAT,
	CHILD_DEVICE_COOL,
	CHILD_DEVICE_FAN,
	CHILD_DEVICE_PIR,
	CHILD_DEVICE_TEMP,
	CHILD_DEVICE_SCREEN,
	CHILD_DEVICE_SCHEDULER,
	CHILD_DEVICE_WEBSERVER
]

CHILD_DEVICE_SUFFIX_UICONTROL		= "Control"

MSG_SUBTYPE_NAME					= "sketchName"
MSG_SUBTYPE_VERSION					= "sketchVersion"
MSG_SUBTYPE_BINARY_STATUS			= "binaryStatus"
MSG_SUBTYPE_TRIPPED					= "armed"
MSG_SUBTYPE_ARMED					= "tripped"
MSG_SUBTYPE_TEMPERATURE				= "temperature"
MSG_SUBTYPE_FORECAST				= "forecast"
MSG_SUBTYPE_CUSTOM					= "custom"
MSG_SUBTYPE_TEXT					= "text"


##############################################################################
#                                                                            #
#       Settings                                                             #
#                                                                            #
##############################################################################

THERMOSTAT_VERSION = "1.9.9"

# Debug settings

debug = False
useTestSchedule = False


# Threading Locks

thermostatLock = threading.RLock()
weatherLock    = threading.Lock()
scheduleLock   = threading.RLock()


# Thermostat persistent settings

settings = JsonStore( "thermostat_settings.json" )
state 	 = JsonStore( "thermostat_state.json" )


# MQTT settings/setup

def mqtt_on_connect( client, userdata, flags, rc ):
	global mqttReconnect

	print( "MQTT Connected with result code: " + str( rc ) )

	if rc == 0:
		if mqttReconnect:
			log( LOG_LEVEL_STATE, CHILD_DEVICE_MQTT, MSG_SUBTYPE_TEXT, "Reconnected to: " + mqttServer + ":" + str( mqttPort ) )
		else:
			mqttReconnect = True
			log( LOG_LEVEL_STATE, CHILD_DEVICE_MQTT, MSG_SUBTYPE_TEXT, "Connected to: " + mqttServer + ":" + str( mqttPort ) )

		src = 	client.subscribe( [
									( mqttSub_restart, 0 ), 	# Subscribe to restart commands
									( mqttSub_loglevel, 0 ),	# Subscribe to log level commands 
									( mqttSub_version, 0 )		# Subscribe to version commands 
								  ] )
		
		if src[ 0 ] == 0:
			log( LOG_LEVEL_INFO, CHILD_DEVICE_MQTT, MSG_SUBTYPE_TEXT, "Subscribe Succeeded: " + mqttServer + ":" + str( mqttPort ) )
		else:
			log( LOG_LEVEL_ERROR, CHILD_DEVICE_MQTT, MSG_SUBTYPE_TEXT, "Subscribe FAILED, result code: " + src[ 0 ] )


if mqttAvailable:
	mqttReconnect		= False
	mqttEnabled    		= False 		if not( settings.exists( "mqtt" ) ) else settings.get( "mqtt" )[ "enabled" ]
	mqttClientID     	= 'thermostat' 	if not( settings.exists( "mqtt" ) ) else settings.get( "mqtt" )[ "clientID" ]
	mqttServer     		= 'localhost' 	if not( settings.exists( "mqtt" ) ) else settings.get( "mqtt" )[ "server" ]
	mqttPort       		= 1883 			if not( settings.exists( "mqtt" ) ) else settings.get( "mqtt" )[ "port" ]
	mqttPubPrefix     	= "thermostat" 	if not( settings.exists( "mqtt" ) ) else settings.get( "mqtt" )[ "pubPrefix" ]

	mqttSub_version		= str( mqttPubPrefix + "/" + mqttClientID + "/command/version" )
	mqttSub_restart		= str( mqttPubPrefix + "/" + mqttClientID + "/command/restart" )
	mqttSub_loglevel	= str( mqttPubPrefix + "/" + mqttClientID + "/command/loglevel" )
	
else:
	mqttEnabled    = False

if mqttEnabled:
	mqttc = mqtt.Client( mqttClientID )
	mqttc.on_connect = mqtt_on_connect

	mqttc.message_callback_add( mqttSub_restart, lambda client, userdata, message: restart() )
	mqttc.message_callback_add( mqttSub_loglevel, lambda client, userdata, message: setLogLevel( message ) )
	mqttc.message_callback_add( mqttSub_version, lambda client, userdata, message: getVersion() )


# Logging settings/setup

LOG_FILE_NAME = "thermostat.log"

LOG_ALWAYS_TIMESTAMP = True

LOG_LEVEL_DEBUG = 1
LOG_LEVEL_INFO	= 2
LOG_LEVEL_ERROR = 3
LOG_LEVEL_STATE = 4
LOG_LEVEL_NONE  = 5

LOG_LEVELS = {
	"debug": LOG_LEVEL_DEBUG,
	"info":  LOG_LEVEL_INFO,
	"state": LOG_LEVEL_STATE,
	"error": LOG_LEVEL_ERROR
}

LOG_LEVELS_STR = { v: k for k, v in LOG_LEVELS.items() }

logFile = None


def log_dummy( level, child_device, msg_subtype, msg, msg_type=MSG_TYPE_SET, timestamp=True, single=False ):
	pass


def log_mqtt( level, child_device, msg_subtype, msg, msg_type=MSG_TYPE_SET, timestamp=True, single=False ):
	if level >= logLevel:
		ts = datetime.datetime.now().strftime( "%Y-%m-%dT%H:%M:%S%z " ) if LOG_ALWAYS_TIMESTAMP or timestamp else ""
		topic = mqttPubPrefix + "/sensor/log/" + LOG_LEVELS_STR[ level ] + "/" + mqttClientID + "/" + child_device + "/" + msg_type + "/" + msg_subtype 
		payload = ts + msg

		if single:
			publish.single( topic, payload, hostname=mqttServer, port=mqttPort, client_id=mqttClientID )
		else:
			mqttc.publish( topic, payload )
		

def log_file( level, child_device, msg_subtype, msg, msg_type=MSG_TYPE_SET, timestamp=True, single=False ):
	if level >= logLevel:
		ts = datetime.datetime.now().strftime( "%Y-%m-%dT%H:%M:%S%z " ) 
		logFile.write( ts + LOG_LEVELS_STR[ level ] + "/" + child_device + "/" + msg_type + "/" + msg_subtype + ": " + msg + "\n" )


def log_print( level, child_device, msg_subtype, msg, msg_type=MSG_TYPE_SET, timestamp=True, single=False ):
	if level >= logLevel:
		ts = datetime.datetime.now().strftime( "%Y-%m-%dT%H:%M:%S%z " ) if LOG_ALWAYS_TIMESTAMP or timestamp else ""
		print( ts + LOG_LEVELS_STR[ level ] + "/" + child_device + "/" + msg_type + "/" + msg_subtype + ": " + msg )


loggingChannel = "none" if not( settings.exists( "logging" ) ) else settings.get( "logging" )[ "channel" ]
loggingLevel   = "state" if not( settings.exists( "logging" ) ) else settings.get( "logging" )[ "level" ]

for case in switch( loggingChannel ):
	if case( 'none' ):
		log = log_dummy
		break
	if case( 'mqtt' ):
		if mqttEnabled:
			log = log_mqtt
		else:
			log = log_dummy	
		break
	if case( 'file' ):
		log = log_file
		logFile = open( LOG_FILE_NAME, "a", 0 )
		break
	if case( 'print' ):
		log = log_print
		break
	if case():		# default
		log = log_dummy	

logLevel = LOG_LEVELS.get( loggingLevel, LOG_LEVEL_NONE )

if mqttEnabled:
	# Make sure we can reach the mqtt server by pinging it
	pingCount = 0;
	pingCmd	  = "ping -c 1 " + mqttServer

	while os.system( pingCmd ) != 0 and pingCount <= 100:
		++pingCount
		time.sleep( 1 )

	mqttc.connect( mqttServer, mqttPort )
	mqttc.loop_start()

# Send presentations for Node

log( LOG_LEVEL_STATE, CHILD_DEVICE_NODE, MSG_SUBTYPE_NAME, "Thermostat Starting Up...", msg_type=MSG_TYPE_PRESENTATION )
log( LOG_LEVEL_STATE, CHILD_DEVICE_NODE, MSG_SUBTYPE_VERSION, THERMOSTAT_VERSION, msg_type=MSG_TYPE_PRESENTATION )

#send presentations for all other child "sensors"

for i in range( len( CHILD_DEVICES ) ):
	child = CHILD_DEVICES[ i ]
	if child != CHILD_DEVICE_NODE:
		log( LOG_LEVEL_STATE, child, child, "", msg_type=MSG_TYPE_PRESENTATION )

# Various temperature settings:

tempScale		  = settings.get( "scale" )[ "tempScale" ]
scaleUnits 	  	  = "c" if tempScale == "metric" else "f"
precipUnits	      = " mm" if tempScale == "metric" else '"'
precipFactor	  = 1.0 if tempScale == "metric" else 0.0393701
precipRound 	  = 0 if tempScale == "metric" else 1
sensorUnits		  = W1ThermSensor.DEGREES_C if tempScale == "metric" else W1ThermSensor.DEGREES_F
windFactor		  = 3.6 if tempScale == "metric" else 1.0
windUnits		  = " km/h" if tempScale == "metric" else " mph"

TEMP_TOLERANCE	  = 0.1 if tempScale == "metric" else 0.18

currentTemp       = 22.0 if tempScale == "metric" else 72.0
priorCorrected    = -100.0
setTemp           = 22.0 if not( state.exists( "state" ) ) else state.get( "state" )[ "setTemp" ]

tempHysteresis    = 0.5  if not( settings.exists( "thermostat" ) ) else settings.get( "thermostat" )[ "tempHysteresis" ]

tempCheckInterval = 3    if not( settings.exists( "thermostat" ) ) else settings.get( "thermostat" )[ "tempCheckInterval" ]

minUIEnabled 	  = 0    if not( settings.exists( "thermostat" ) ) else settings.get( "thermostat" )[ "minUIEnabled" ]
minUITimeout 	  = 3    if not( settings.exists( "thermostat" ) ) else settings.get( "thermostat" )[ "minUITimeout" ]
minUITimer		  = None

log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/temperature/tempScale", str( tempScale ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/temperature/scaleUnits", str( scaleUnits ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/temperature/precipUnits", str( precipUnits ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/temperature/precipFactor", str( precipFactor ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/temperature/sensorUnits", str( sensorUnits ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/temperature/windFactor", str( windFactor ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/temperature/windUnits", str( windUnits ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/temperature/currentTemp", str( currentTemp ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/temperature/setTemp", str( setTemp ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/temperature/tempHysteresis", str( tempHysteresis ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/temperature/tempCheckInterval", str( tempCheckInterval ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/temperature/minUIEnabled", str( minUIEnabled ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/temperature/minUITimeout", str( minUITimeout ), timestamp=False )


# Temperature calibration settings:

elevation		  = 0 if not( settings.exists( "thermostat" ) ) else settings.get( "calibration" )[ "elevation" ]
boilingPoint	  = ( 100.0 - 0.003353 * elevation ) if tempScale == "metric" else ( 212.0 - 0.00184 * elevation )
freezingPoint	  = 0.01 if tempScale == "metric" else 32.018
referenceRange	  = boilingPoint - freezingPoint

boilingMeasured   = settings.get( "calibration" )[ "boilingMeasured" ]
freezingMeasured  = settings.get( "calibration" )[ "freezingMeasured" ]
measuredRange	  = boilingMeasured - freezingMeasured

log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/calibration/elevation", str( elevation ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/calibration/boilingPoint", str( boilingPoint ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/calibration/freezingPoint", str( freezingPoint ), timestamp=False )
log( LOG_LEVEL_DEBUG, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/calibration/referenceRange", str( referenceRange ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/calibration/boilingMeasured", str( boilingMeasured ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/calibration/freezingMeasured", str( freezingMeasured ), timestamp=False )
log( LOG_LEVEL_DEBUG, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/calibration/measuredRange", str( measuredRange ), timestamp=False )


# UI Slider settings:

minTemp			  = 15.0 if not( settings.exists( "thermostat" ) ) else settings.get( "thermostat" )[ "minTemp" ]
maxTemp			  = 30.0 if not( settings.exists( "thermostat" ) ) else settings.get( "thermostat" )[ "maxTemp" ]
tempStep		  = 0.5  if not( settings.exists( "thermostat" ) ) else settings.get( "thermostat" )[ "tempStep" ]

log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/UISlider/minTemp", str( minTemp ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/UISlider/maxTemp", str( maxTemp ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/UISlider/tempStep", str( tempStep ), timestamp=False )

try:
	tempSensor = W1ThermSensor()
except:
	tempSensor = None


# PIR (Motion Sensor) setup:

pirEnabled 			= 0 if not( settings.exists( "pir" ) ) else settings.get( "pir" )[ "pirEnabled" ]
pirPin  			= 5 if not( settings.exists( "pir" ) ) else settings.get( "pir" )[ "pirPin" ]

pirCheckInterval 	= 0.5 if not( settings.exists( "pir" ) ) else settings.get( "pir" )[ "pirCheckInterval" ]

pirIgnoreFromStr	= "00:00" if not( settings.exists( "pir" ) ) else settings.get( "pir" )[ "pirIgnoreFrom" ]
pirIgnoreToStr		= "00:00" if not( settings.exists( "pir" ) ) else settings.get( "pir" )[ "pirIgnoreTo" ]

pirIgnoreFrom		= datetime.time( int( pirIgnoreFromStr.split( ":" )[ 0 ] ), int( pirIgnoreFromStr.split( ":" )[ 1 ] ) )
pirIgnoreTo			= datetime.time( int( pirIgnoreToStr.split( ":" )[ 0 ] ), int( pirIgnoreToStr.split( ":" )[ 1 ] ) )

log( LOG_LEVEL_INFO, CHILD_DEVICE_PIR, MSG_SUBTYPE_ARMED, str( pirEnabled ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/pir/checkInterval", str( pirCheckInterval ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/pir/ignoreFrom", str( pirIgnoreFromStr ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/pir/ignoreTo", str( pirIgnoreToStr ), timestamp=False )

# GPIO Pin setup and utility routines:

coolPin		 		= 18 if not( settings.exists( "thermostat" ) ) else settings.get( "thermostat" )[ "coolPin" ]
heatPin 			= 23 if not( settings.exists( "thermostat" ) ) else settings.get( "thermostat" )[ "heatPin" ]
fanPin  			= 25 if not( settings.exists( "thermostat" ) ) else settings.get( "thermostat" )[ "fanPin" ]

GPIO.setmode( GPIO.BCM )
GPIO.setup( coolPin, GPIO.OUT )
GPIO.output( coolPin, GPIO.LOW )
GPIO.setup( heatPin, GPIO.OUT )
GPIO.output( heatPin, GPIO.LOW )
GPIO.setup( fanPin, GPIO.OUT )
GPIO.output( fanPin, GPIO.LOW )

if pirEnabled:
	GPIO.setup( pirPin, GPIO.IN )

CHILD_DEVICE_HEAT					= "heat"
CHILD_DEVICE_COOL					= "cool"
CHILD_DEVICE_FAN					= "fan"

log( LOG_LEVEL_INFO, CHILD_DEVICE_COOL, MSG_SUBTYPE_BINARY_STATUS, str( coolPin ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_HEAT, MSG_SUBTYPE_BINARY_STATUS, str( heatPin ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_FAN, MSG_SUBTYPE_BINARY_STATUS, str( fanPin ), timestamp=False )
log( LOG_LEVEL_INFO, CHILD_DEVICE_PIR, MSG_SUBTYPE_TRIPPED, str( pirPin ), timestamp=False )


##############################################################################
#                                                                            #
#       UI Controls/Widgets                                                  #
#                                                                            #
##############################################################################

controlColours = {
					"normal": ( 1.0, 1.0, 1.0, 1.0 ),
					"Cool":   ( 0.0, 0.0, 1.0, 0.4 ),
					"Heat":   ( 1.0, 0.0, 0.0, 1.0 ),
					"Fan":    ( 0.0, 1.0, 0.0, 0.4 ),
					"Hold":   ( 0.0, 1.0, 0.0, 0.4 ),					
				 }


def setControlState( control, state ):
	with thermostatLock:
		control.state = state
		if state == "normal":
			control.background_color = controlColours[ "normal" ]
		else:
			control.background_color = controlColours[ control.text.replace( "[b]", "" ).replace( "[/b]", "" ) ]
		
		controlLabel = control.text.replace( "[b]", "" ).replace( "[/b]", "" ).lower()
		log( LOG_LEVEL_STATE, controlLabel +  CHILD_DEVICE_SUFFIX_UICONTROL, MSG_SUBTYPE_BINARY_STATUS, "0" if state == "normal" else "1" )


coolControl = ToggleButton( text="[b]Cool[/b]", 
							markup=True, 
							size_hint = ( None, None )
						  )

setControlState( coolControl, "normal" if not( state.exists( "state" ) ) else state.get( "state" )[ "coolControl" ] )

heatControl = ToggleButton( text="[b]Heat[/b]", 
							markup=True, 
							size_hint = ( None, None )
						  )

setControlState( heatControl, "normal" if not( state.exists( "state" ) ) else state.get( "state" )[ "heatControl" ] )

fanControl  = ToggleButton( text="[b]Fan[/b]", 
							markup=True, 
							size_hint = ( None, None )
						  )

setControlState( fanControl, "normal" if not( state.exists( "state" ) ) else state.get( "state" )[ "fanControl" ] )

holdControl = ToggleButton( text="[b]Hold[/b]", 
							markup=True, 
							size_hint = ( None, None )
						  )

setControlState( holdControl, "normal" if not( state.exists( "state" ) ) else state.get( "state" )[ "holdControl" ] )



def get_status_string():
	with thermostatLock:
		sched = "None"

		if holdControl.state == "down":
			sched = "Hold"
		elif useTestSchedule:
			sched = "Test"
		elif heatControl.state == "down":
			sched = "Heat"
		elif coolControl.state == "down":
			sched = "Cool"
	
		return "[b]System:[/b]\n  " + \
			   "Heat:     " + ( "[color=00ff00][b]On[/b][/color]" if GPIO.input( heatPin ) else "Off" ) + "\n  " + \
		       "Cool:      " + ( "[color=00ff00][b]On[/b][/color]" if GPIO.input( coolPin ) else "Off" ) + "\n  " + \
		       "Fan:       " + ( "[color=00ff00][b]On[/b][/color]" if GPIO.input( fanPin ) else "Auto" ) + "\n  " + \
			   "Sched:   " + sched


versionLabel = Label( text="Thermostat v" + str( THERMOSTAT_VERSION ), size_hint = ( None, None ), font_size='10sp', markup=True, text_size=( 150, 20 ) )
currentLabel = Label( text="[b]" + str( currentTemp ) + scaleUnits + "[/b]", size_hint = ( None, None ), font_size='100sp', markup=True, text_size=( 300, 200 ) )
altCurLabel	 = Label( text=currentLabel.text, size_hint = ( None, None ), font_size='100sp', markup=True, text_size=( 300, 200 ), color=( 0.4, 0.4, 0.4, 0.2 ) )

setLabel     = Label( text="  Set\n[b]" + str( setTemp ) + scaleUnits + "[/b]", size_hint = ( None, None ), font_size='25sp', markup=True, text_size=( 100, 100 ) )
statusLabel  = Label( text=get_status_string(), size_hint = ( None, None ),  font_size='20sp', markup=True, text_size=( 140, 130 ) )

dateLabel	 = Label( text="[b]" + time.strftime("%a %b %d, %Y") + "[/b]", size_hint = ( None, None ), font_size='20sp', markup=True, text_size=( 270, 40 ) )

timeStr		 = time.strftime("%I:%M %p").lower()

timeLabel	 = Label( text="[b]" + ( timeStr if timeStr[0:1] != "0" else timeStr[1:] ) + "[/b]", size_hint = ( None, None ), font_size='40sp', markup=True, text_size=( 180, 75 ) )
altTimeLabel = Label( text=timeLabel.text, size_hint = ( None, None ), font_size='40sp', markup=True, text_size=( 180, 75 ), color=( 0.4, 0.4, 0.4, 0.2 ) )

tempSlider 	 = Slider( orientation='vertical', min=minTemp, max=maxTemp, step=tempStep, value=setTemp, size_hint = ( None, None ) )

screenMgr    = None


##############################################################################
#                                                                            #
#       Weather functions/constants/widgets                                  #
#                                                                            #
##############################################################################

weatherLocation 	 = settings.get( "weather" )[ "location" ]
weatherAppKey		 = settings.get( "weather" )[ "appkey" ]
weatherURLBase  	 = "http://api.openweathermap.org/data/2.5/"
weatherURLCurrent 	 = weatherURLBase + "weather?units=" + tempScale + "&q=" + weatherLocation + "&APPID=" + weatherAppKey
weatherURLForecast 	 = weatherURLBase + "forecast/daily?units=" + tempScale + "&q=" + weatherLocation + "&APPID=" + weatherAppKey
weatherURLTimeout 	 = settings.get( "weather" )[ "URLtimeout" ]

weatherRefreshInterval   = settings.get( "weather" )[ "weatherRefreshInterval" ] * 60  
forecastRefreshInterval  = settings.get( "weather" )[ "forecastRefreshInterval" ] * 60  
weatherExceptionInterval = settings.get( "weather" )[ "weatherExceptionInterval" ] * 60  

weatherSummaryLabel  = Label( text="", size_hint = ( None, None ), font_size='20sp', markup=True, text_size=( 200, 20 ) )
weatherDetailsLabel  = Label( text="", size_hint = ( None, None ), font_size='20sp', markup=True, text_size=( 300, 150 ), valign="top" )
weatherImg           = Image( source="web/images/na.png", size_hint = ( None, None ) )

forecastTodaySummaryLabel = Label( text="", size_hint = ( None, None ), font_size='15sp',  markup=True, text_size=( 100, 15 ) )
forecastTodayDetailsLabel = Label( text="", size_hint = ( None, None ), font_size='15sp',  markup=True, text_size=( 200, 150 ), valign="top" )
forecastTodayImg   		  = Image( source="web/images/na.png", size_hint = ( None, None ) )
forecastTomoSummaryLabel  = Label( text="", size_hint = ( None, None ), font_size='15sp', markup=True, text_size=( 100, 15 ))
forecastTomoDetailsLabel  = Label( text="", size_hint = ( None, None ), font_size='15sp', markup=True, text_size=( 200, 150 ), valign="top" )
forecastTomoImg    		  = Image( source="web/images/na.png", size_hint = ( None, None ) )


def get_weather( url ):
	return json.loads( urllib2.urlopen( url, None, weatherURLTimeout ).read() )


def get_cardinal_direction( heading ):
	directions = [ "N", "NE", "E", "SE", "S", "SW", "W", "NW", "N" ]
	return directions[ int( round( ( ( heading % 360 ) / 45 ) ) ) ]


def display_current_weather( dt ):
	with weatherLock:
		interval = weatherRefreshInterval

		try:
			weather = get_weather( weatherURLCurrent )

			weatherImg.source = "web/images/" + weather[ "weather" ][ 0 ][ "icon" ] + ".png" 
	
			weatherSummaryLabel.text = "[b]" + weather[ "weather" ][ 0 ][ "description" ].title() + "[/b]"

			weatherDetailsLabel.text = "\n".join( (
				"Temp:       " + str( int( round( weather[ "main" ][ "temp" ], 0 ) ) ) + scaleUnits,
				"Humidity: " + str( weather[ "main" ][ "humidity" ] ) + "%",
				"Wind:        " + str( int( round( weather[ "wind" ][ "speed" ] * windFactor ) ) ) + windUnits + " " + get_cardinal_direction( weather[ "wind" ][ "deg" ] ),
				"Clouds:     " + str( weather[ "clouds" ][ "all" ] ) + "%",
				"Sun:           " + time.strftime("%H:%M", time.localtime( weather[ "sys" ][ "sunrise" ] ) ) + " am, " + time.strftime("%I:%M", time.localtime( weather[ "sys" ][ "sunset" ] ) ) + " pm"
			) )

			
			log( LOG_LEVEL_INFO, CHILD_DEVICE_WEATHER_CURR, MSG_SUBTYPE_TEXT, weather[ "weather" ][ 0 ][ "description" ].title() + "; " + re.sub( '\n', "; ", re.sub( ' +', ' ', weatherDetailsLabel.text ).strip() ) )

		except:
			interval = weatherExceptionInterval

			weatherImg.source = "web/images/na.png"
			weatherSummaryLabel.text = ""
			weatherDetailsLabel.text = ""

			log( LOG_LEVEL_ERROR, CHILD_DEVICE_WEATHER_CURR, MSG_SUBTYPE_TEXT, "Update FAILED!" )

		Clock.schedule_once( display_current_weather, interval )


def get_precip_amount( raw ):
	precip = round( raw * precipFactor, precipRound )

	if tempScale == "metric":
		return str( int ( precip ) )
	else:
		return str( precip )


def display_forecast_weather( dt ):
	with weatherLock:
		interval = forecastRefreshInterval

		try:
			forecast = get_weather( weatherURLForecast )

			today    = forecast[ "list" ][ 0 ]
			tomo     = forecast[ "list" ][ 1 ]

			forecastTodayImg.source = "web/images/" + today[ "weather" ][ 0 ][ "icon" ] + ".png" 

			forecastTodaySummaryLabel.text = "[b]" + today[ "weather" ][ 0 ][ "description" ].title() + "[/b]"		
	
			todayText = "\n".join( (
				"High:         " + str( int( round( today[ "temp" ][ "max" ], 0 ) ) ) + scaleUnits + ", Low: " + str( int( round( today[ "temp" ][ "min" ], 0 ) ) ) + scaleUnits,
				"Humidity: " + str( today[ "humidity" ] ) + "%",
				"Wind:        " + str( int( round( today[ "speed" ] * windFactor ) ) ) + windUnits + " " + get_cardinal_direction( today[ "deg" ] ),
				"Clouds:     " + str( today[ "clouds" ] ) + "%",
			) )

			if "rain" in today or "snow" in today:
				todayText += "\n"
				if "rain" in today:
					todayText += "Rain:         " + get_precip_amount( today[ "rain" ] ) + precipUnits   
					if "snow" in today:
						todayText += ", Snow: " + get_precip_amount( today[ "snow" ] ) + precipUnits
				else:
					todayText += "Snow:         " + get_precip_amount( today[ "snow" ] ) + precipUnits

			forecastTodayDetailsLabel.text = todayText;

			forecastTomoImg.source = "web/images/" + tomo[ "weather" ][ 0 ][ "icon" ] + ".png" 

			forecastTomoSummaryLabel.text = "[b]" + tomo[ "weather" ][ 0 ][ "description" ].title() + "[/b]"		
	
			tomoText = "\n".join( (
				"High:         " + str( int( round( tomo[ "temp" ][ "max" ], 0 ) ) ) + scaleUnits + ", Low: " + str( int( round( tomo[ "temp" ][ "min" ], 0 ) ) ) + scaleUnits,
				"Humidity: " + str( tomo[ "humidity" ] ) + "%",
				"Wind:        " + str( int( round( tomo[ "speed" ] * windFactor ) ) ) + windUnits + " " + get_cardinal_direction( tomo[ "deg" ] ),
				"Clouds:     " + str( tomo[ "clouds" ] ) + "%",
			) )

			if "rain" in tomo or "snow" in tomo:
				tomoText += "\n"
				if "rain" in tomo:
					tomoText += "Rain:         " + get_precip_amount( tomo[ "rain" ] ) + precipUnits
					if "snow" in tomo:
						tomoText += ", Snow: " + get_precip_amount( tomo[ "snow" ] ) + precipUnits
				else:
					tomoText += "Snow:         " + get_precip_amount( tomo[ "snow" ] ) + precipUnits

			forecastTomoDetailsLabel.text = tomoText

			log( LOG_LEVEL_INFO, CHILD_DEVICE_WEATHER_FCAST_TODAY, MSG_SUBTYPE_TEXT, today[ "weather" ][ 0 ][ "description" ].title() + "; " + re.sub( '\n', "; ", re.sub( ' +', ' ', forecastTodayDetailsLabel.text ).strip() ) )
			log( LOG_LEVEL_INFO, CHILD_DEVICE_WEATHER_FCAST_TOMO, MSG_SUBTYPE_TEXT, tomo[ "weather" ][ 0 ][ "description" ].title() + "; " + re.sub( '\n', "; ", re.sub( ' +', ' ', forecastTomoDetailsLabel.text ).strip() ) )

		except:
			interval = weatherExceptionInterval

			forecastTodayImg.source = "web/images/na.png"
			forecastTodaySummaryLabel.text = ""
			forecastTodayDetailsLabel.text = ""
			forecastTomoImg.source = "web/images/na.png"
			forecastTomoSummaryLabel.text = ""
			forecastTomoDetailsLabel.text = ""

			log( LOG_LEVEL_ERROR, CHILD_DEVICE_WEATHER_FCAST_TODAY, MSG_SUBTYPE_TEXT, "Update FAILED!" )

		Clock.schedule_once( display_forecast_weather, interval )


##############################################################################
#                                                                            #
#       Utility Functions                                                    #
#                                                                            #
##############################################################################

def get_ip_address():
	s = socket.socket( socket.AF_INET, socket.SOCK_DGRAM )
	s.settimeout( 10 )   # 10 seconds
	try:
		s.connect( ( "8.8.8.8", 80 ) )    # Google DNS server
		ip = s.getsockname()[0] 
		log( LOG_LEVEL_INFO, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM +"/settings/ip", ip, timestamp=False )
	except socket.error:
		ip = "127.0.0.1"
		log( LOG_LEVEL_ERROR, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/settings/ip", "FAILED to get ip address, returning " + ip, timestamp=False )

	return ip


def getVersion():
	log( LOG_LEVEL_STATE, CHILD_DEVICE_NODE, MSG_SUBTYPE_VERSION, THERMOSTAT_VERSION )


def restart():
	log( LOG_LEVEL_STATE, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/restart", "Thermostat restarting...", single=True ) 
	GPIO.cleanup()

	if logFile is not None:
		logFile.flush()
		os.fsync( logFile.fileno() )
		logFile.close()

	if mqttEnabled:	
		mqttc.disconnect()

	os.execl( sys.executable, 'python', __file__, *sys.argv[1:] )	# This does not return!!!


def setLogLevel( msg ):
	global logLevel

	if LOG_LEVELS.get( msg.payload ):
		log( LOG_LEVEL_STATE, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/loglevel", "LogLevel set to: " + msg.payload ) 

		logLevel = LOG_LEVELS.get( msg.payload, logLevel )
	else:
		log( LOG_LEVEL_ERROR, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/loglevel", "Invalid LogLevel: " + msg.payload ) 


##############################################################################
#                                                                            #
#       Thermostat Implementation                                            #
#                                                                            #
##############################################################################

# Main furnace/AC system control function:

def change_system_settings():
	with thermostatLock:
		hpin_start = str( GPIO.input( heatPin ) )
		cpin_start = str( GPIO.input( coolPin ) )
		fpin_start = str( GPIO.input( fanPin ) )

		if heatControl.state == "down":
			GPIO.output( coolPin, GPIO.LOW )

			if setTemp >= currentTemp + tempHysteresis:
				GPIO.output( heatPin, GPIO.HIGH )
				GPIO.output( fanPin, GPIO.HIGH )	
			elif setTemp <= currentTemp:
				GPIO.output( heatPin, GPIO.LOW )
				if fanControl.state != "down" and not GPIO.input( coolPin ):
					GPIO.output( fanPin, GPIO.LOW )			
		else:
			GPIO.output( heatPin, GPIO.LOW )

			if coolControl.state == "down":
				if setTemp <= currentTemp - tempHysteresis:
					GPIO.output( coolPin, GPIO.HIGH )
					GPIO.output( fanPin, GPIO.HIGH )
				elif setTemp >= currentTemp:
					GPIO.output( coolPin, GPIO.LOW )
					if fanControl.state != "down" and not GPIO.input( heatPin ):
						GPIO.output( fanPin, GPIO.LOW )					
			else:
				GPIO.output( coolPin, GPIO.LOW )
				if fanControl.state != "down" and not GPIO.input( heatPin ):
					GPIO.output( fanPin, GPIO.LOW )

		if fanControl.state == "down":
			GPIO.output( fanPin, GPIO.HIGH )
		else:
			if not GPIO.input( heatPin ) and not GPIO.input( coolPin ):
				GPIO.output( fanPin, GPIO.LOW )

		# save the thermostat state in case of restart
		state.put( "state",	setTemp=setTemp, 
					  		heatControl=heatControl.state, coolControl=coolControl.state, fanControl=fanControl.state, holdControl=holdControl.state
		)

		statusLabel.text = get_status_string()

		if hpin_start != str( GPIO.input( heatPin ) ):
			log( LOG_LEVEL_STATE, CHILD_DEVICE_HEAT, MSG_SUBTYPE_BINARY_STATUS, "1" if GPIO.input( heatPin ) else "0" )
		if cpin_start != str( GPIO.input( coolPin ) ):
			log( LOG_LEVEL_STATE, CHILD_DEVICE_COOL, MSG_SUBTYPE_BINARY_STATUS, "1" if GPIO.input( coolPin ) else "0" )
		if fpin_start != str( GPIO.input( fanPin ) ):
			log( LOG_LEVEL_STATE, CHILD_DEVICE_FAN, MSG_SUBTYPE_BINARY_STATUS, "1" if GPIO.input( fanPin ) else "0" )


# This callback will be bound to the touch screen UI buttons:

def control_callback( control ):
	with thermostatLock:
		setControlState( control, control.state ) 	# make sure we change the background colour!

		if control is coolControl:
			if control.state == "down":
				setControlState( heatControl, "normal" )
			reloadSchedule()
			
		if control is heatControl:
			if control.state == "down":
				setControlState( coolControl, "normal" )	
			reloadSchedule()						
		

# Check the current sensor temperature

def check_sensor_temp( dt ):
	with thermostatLock:
		global currentTemp, priorCorrected
		global tempSensor
		
		if tempSensor is not None:
			rawTemp = tempSensor.get_temperature( sensorUnits )
			correctedTemp = ( ( ( rawTemp - freezingMeasured ) * referenceRange ) / measuredRange ) + freezingPoint
			currentTemp = round( correctedTemp, 1 )
			log( LOG_LEVEL_DEBUG, CHILD_DEVICE_TEMP, MSG_SUBTYPE_CUSTOM + "/raw", str( rawTemp ) )
			log( LOG_LEVEL_DEBUG, CHILD_DEVICE_TEMP, MSG_SUBTYPE_CUSTOM + "/corrected", str( correctedTemp ) )

			if abs( priorCorrected - correctedTemp ) >= TEMP_TOLERANCE:
				log( LOG_LEVEL_STATE, CHILD_DEVICE_TEMP, MSG_SUBTYPE_TEMPERATURE, str( currentTemp ) )	
				priorCorrected = correctedTemp	

		currentLabel.text = "[b]" + str( currentTemp ) + scaleUnits + "[/b]"
		altCurLabel.text  = currentLabel.text

		dateLabel.text      = "[b]" + time.strftime("%a %b %d, %Y") + "[/b]"

		timeStr		 = time.strftime("%I:%M %p").lower()

		timeLabel.text      = ( "[b]" + ( timeStr if timeStr[0:1] != "0" else timeStr[1:] ) + "[/b]" ).lower()
		altTimeLabel.text  	= timeLabel.text

		change_system_settings()


# This is called when the desired temp slider is updated:

def update_set_temp( slider, value ):
	with thermostatLock:
		global setTemp
		priorTemp = setTemp
		setTemp = round( slider.value, 1 )
		setLabel.text = "  Set\n[b]" + str( setTemp ) + scaleUnits + "[/b]"
		if priorTemp != setTemp:
			log( LOG_LEVEL_STATE, CHILD_DEVICE_UICONTROL_SLIDER, MSG_SUBTYPE_TEMPERATURE, str( setTemp ) )


# Check the PIR motion sensor status

def check_pir( pin ):
	global minUITimer

	with thermostatLock:
		if GPIO.input( pirPin ): 
			log( LOG_LEVEL_INFO, CHILD_DEVICE_PIR, MSG_SUBTYPE_TRIPPED, "1" )

			if minUITimer != None:
				  Clock.unschedule( show_minimal_ui )

			minUITimer = Clock.schedule_once( show_minimal_ui, minUITimeout ) 

			ignore = False
			now = datetime.datetime.now().time()
			
			if pirIgnoreFrom > pirIgnoreTo:
				if now >= pirIgnoreFrom or now < pirIgnoreTo:
					ignore = True
			else:
				if now >= pirIgnoreFrom and now < pirIgnoreTo:
					ignore = True

			if screenMgr.current == "minimalUI" and not( ignore ):
				screenMgr.current = "thermostatUI"
				log( LOG_LEVEL_DEBUG, CHILD_DEVICE_SCREEN, MSG_SUBTYPE_TEXT, "Full" )
	
		else:
			log( LOG_LEVEL_DEBUG, CHILD_DEVICE_PIR, MSG_SUBTYPE_TRIPPED, "0" )


# Minimal UI Display functions and classes

def show_minimal_ui( dt ):
	with thermostatLock:
		screenMgr.current = "minimalUI"
		log( LOG_LEVEL_DEBUG, CHILD_DEVICE_SCREEN, MSG_SUBTYPE_TEXT, "Minimal" )


class MinimalScreen( Screen ):
	def on_touch_down( self, touch ):
		if self.collide_point( *touch.pos ):
			touch.grab( self )
			return True

	def on_touch_up( self, touch ):
		global minUITimer

		if touch.grab_current is self:
			touch.ungrab( self )
			with thermostatLock:
				if minUITimer != None:
					Clock.unschedule( show_minimal_ui )
				minUITimer = Clock.schedule_once( show_minimal_ui, minUITimeout )
				self.manager.current = "thermostatUI"
				log( LOG_LEVEL_DEBUG, CHILD_DEVICE_SCREEN, MSG_SUBTYPE_TEXT, "Full" )
			return True


##############################################################################
#                                                                            #
#       Kivy Thermostat App class                                            #
#                                                                            #
##############################################################################

class ThermostatApp( App ):

	def build( self ):
		global screenMgr

		# Set up the thermostat UI layout:
		thermostatUI = FloatLayout( size=( 800, 480 ) )

		# Make the background black:
		with thermostatUI.canvas.before:
			Color( 0.0, 0.0, 0.0, 1 )
			self.rect = Rectangle( size=( 800, 480 ), pos=thermostatUI.pos )

		# Create the rest of the UI objects ( and bind them to callbacks, if necessary ):
		
		wimg = Image( source='web/images/logo.png' )
		
		coolControl.bind( on_press=control_callback )		
		heatControl.bind( on_press=control_callback )	
		fanControl.bind( on_press=control_callback )
		holdControl.bind( on_press=control_callback )

		tempSlider.bind( on_touch_down=update_set_temp, on_touch_move=update_set_temp )

       	# set sizing and position info

		wimg.size = ( 80, 80 )
		wimg.size_hint = ( None, None )
		wimg.pos = ( 10, 380 )

		heatControl.size  = ( 80, 80 )
		heatControl.pos = ( 680, 380 )

		coolControl.size  = ( 80, 80 )
		coolControl.pos = ( 680, 270 )

		fanControl.size  = ( 80, 80 )
		fanControl.pos = ( 680, 160 )

		statusLabel.pos = ( 670, 40 )

		tempSlider.size  = ( 100, 360 )
		tempSlider.pos = ( 570, 20 )

		holdControl.size  = ( 80, 80 )
		holdControl.pos = ( 480, 380 )

		setLabel.pos = ( 590, 390 )

		currentLabel.pos = ( 390, 290 )

		dateLabel.pos = ( 180, 370 )
		timeLabel.pos = ( 335, 380 )

		weatherImg.pos = ( 265, 160 )
		weatherSummaryLabel.pos = ( 430, 160 )
		weatherDetailsLabel.pos = ( 395, 60 )

		versionLabel.pos = ( 320, 0 )

		forecastTodayHeading = Label( text="[b]Today[/b]:", font_size='20sp', markup=True, size_hint = ( None, None ), pos = ( 0, 290 ) )
		
		forecastTodayImg.pos = ( 0, 260 )
		forecastTodaySummaryLabel.pos = ( 100, 260 )
		forecastTodayDetailsLabel.pos = ( 80, 167 )

		forecastTomoHeading = Label( text="[b]Tomorrow[/b]:", font_size='20sp', markup=True, size_hint = ( None, None ), pos = ( 20, 130 ) )

		forecastTomoImg.pos = ( 0, 100 )
		forecastTomoSummaryLabel.pos = ( 100, 100 )
		forecastTomoDetailsLabel.pos = ( 80, 7 )

		# Add the UI elements to the thermostat UI layout:
		thermostatUI.add_widget( wimg )
		thermostatUI.add_widget( coolControl )
		thermostatUI.add_widget( heatControl )
		thermostatUI.add_widget( fanControl )
		thermostatUI.add_widget( holdControl )
		thermostatUI.add_widget( tempSlider )
		thermostatUI.add_widget( currentLabel )
		thermostatUI.add_widget( setLabel )
		thermostatUI.add_widget( statusLabel )
		thermostatUI.add_widget( dateLabel )
		thermostatUI.add_widget( timeLabel )
		thermostatUI.add_widget( weatherImg )
		thermostatUI.add_widget( weatherSummaryLabel )
		thermostatUI.add_widget( weatherDetailsLabel )
		thermostatUI.add_widget( versionLabel )
		thermostatUI.add_widget( forecastTodayHeading )
		thermostatUI.add_widget( forecastTodayImg )
		thermostatUI.add_widget( forecastTodaySummaryLabel )
		thermostatUI.add_widget( forecastTodayDetailsLabel )
		thermostatUI.add_widget( forecastTomoHeading )
		thermostatUI.add_widget( forecastTomoImg )
		thermostatUI.add_widget( forecastTomoDetailsLabel )
		thermostatUI.add_widget( forecastTomoSummaryLabel )

		layout = thermostatUI

		# Minimap UI initialization

		if minUIEnabled:
			uiScreen 	= Screen( name="thermostatUI" )
			uiScreen.add_widget( thermostatUI )

			minScreen 	= MinimalScreen( name="minimalUI" )
			minUI 		= FloatLayout( size=( 800, 480 ) )

			with minUI.canvas.before:
				Color( 0.0, 0.0, 0.0, 1 )
				self.rect = Rectangle( size=( 800, 480 ), pos=minUI.pos )

			altCurLabel.pos = ( 390, 290 )
			altTimeLabel.pos = ( 335, 380 )

			minUI.add_widget( altCurLabel )
			minUI.add_widget( altTimeLabel )
			minScreen.add_widget( minUI )

			screenMgr = ScreenManager( transition=NoTransition() )		# FadeTransition seems to have OpenGL bugs in Kivy Dev 1.9.1 and is unstable, so sticking with no transition for now
			screenMgr.add_widget ( uiScreen )
			screenMgr.add_widget ( minScreen )

			layout = screenMgr

			minUITimer = Clock.schedule_once( show_minimal_ui, minUITimeout )

			if pirEnabled:
				Clock.schedule_interval( check_pir, pirCheckInterval )


		# Start checking the temperature
		Clock.schedule_interval( check_sensor_temp, tempCheckInterval )

		# Show the current weather & forecast
		Clock.schedule_once( display_current_weather, 5 )
		Clock.schedule_once( display_forecast_weather, 10 )

		return layout


##############################################################################
#                                                                            #
#       Scheduler Implementation                                             #
#                                                                            #
##############################################################################

def startScheduler():
	log( LOG_LEVEL_INFO, CHILD_DEVICE_SCHEDULER, MSG_SUBTYPE_TEXT, "Started" )
	while True:
		if holdControl.state == "normal":
			with scheduleLock:
				log( LOG_LEVEL_DEBUG, CHILD_DEVICE_SCHEDULER, MSG_SUBTYPE_TEXT, "Running pending" )
				schedule.run_pending()

		time.sleep( 10 )


def setScheduledTemp( temp ):
	with thermostatLock:
		global setTemp
		if holdControl.state == "normal":
			setTemp = round( temp, 1 )
			setLabel.text = "  Set\n[b]" + str( setTemp ) + scaleUnits + "[/b]"
			tempSlider.value = setTemp
			log( LOG_LEVEL_STATE, CHILD_DEVICE_SCHEDULER, MSG_SUBTYPE_TEMPERATURE, str( setTemp ) )


def getTestSchedule():
	days = [ "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday" ]
	testSched = {}
	
	for i in range( len( days ) ):
		tempList = []
		for minute in range( 60 * 24 ):
			hrs, mins = divmod( minute, 60 )
			tempList.append( [
								str( hrs ).rjust( 2, '0' ) + ":" + str( mins ).rjust( 2, '0' ),
								float( i + 1 ) / 10.0 + ( ( 19.0 if tempScale == "metric" else 68.0 ) if minute % 2 == 1 else ( 22.0 if tempScale == "metric" else 72.0 ) )
						   ] )

		testSched[ days[i] ] = tempList

	return testSched


def reloadSchedule():
	with scheduleLock:
		schedule.clear()

		activeSched = None

		with thermostatLock:
			thermoSched = JsonStore( "thermostat_schedule.json" )
	
			if holdControl.state != "down":
				if heatControl.state == "down":
					activeSched = thermoSched[ "heat" ]  
					log( LOG_LEVEL_INFO, CHILD_DEVICE_SCHEDULER, MSG_SUBTYPE_CUSTOM + "/load", "heat" )
				elif coolControl.state == "down":
					activeSched = thermoSched[ "cool" ]  
					log( LOG_LEVEL_INFO, CHILD_DEVICE_SCHEDULER, MSG_SUBTYPE_CUSTOM + "/load", "cool" )

				if useTestSchedule: 
					activeSched = getTestSchedule()
					log( LOG_LEVEL_INFO, CHILD_DEVICE_SCHEDULER, MSG_SUBTYPE_CUSTOM + "/load", "test" )
					print "Using Test Schedule!!!"
	
		if activeSched != None:
			for day, entries in activeSched.iteritems():
				for i, entry in enumerate( entries ):
					getattr( schedule.every(), day ).at( entry[ 0 ] ).do( setScheduledTemp, entry[ 1 ] )
					log( LOG_LEVEL_DEBUG, CHILD_DEVICE_SCHEDULER, MSG_SUBTYPE_TEXT, "Set " + day + ", at: " + entry[ 0 ] + " = " + str( entry[ 1 ] ) + scaleUnits )


##############################################################################
#                                                                            #
#       Web Server Interface                                                 #
#                                                                            #
##############################################################################

class WebInterface( object ):

	@cherrypy.expose
	def index( self ):	
		log( LOG_LEVEL_INFO, CHILD_DEVICE_WEBSERVER, MSG_SUBTYPE_TEXT, "Served thermostat.html to: " + cherrypy.request.remote.ip )	
		file = open( "web/html/thermostat.html", "r" )

		html = file.read()

		file.close()

		with thermostatLock:		

			html = html.replace( "@@version@@", str( THERMOSTAT_VERSION ) )
			html = html.replace( "@@temp@@", str( setTemp ) )
			html = html.replace( "@@current@@", str( currentTemp ) + scaleUnits )
			html = html.replace( "@@minTemp@@", str( minTemp ) )
			html = html.replace( "@@maxTemp@@", str( maxTemp ) )
			html = html.replace( "@@tempStep@@", str( tempStep ) )

		
			status = statusLabel.text.replace( "[b]", "<b>" ).replace( "[/b]", "</b>" ).replace( "\n", "<br>" ).replace( " ", "&nbsp;" )
			status = status.replace( "[color=00ff00]", '<font color="red">' ).replace( "[/color]", '</font>' ) 
	
			html = html.replace( "@@status@@", status )
			html = html.replace( "@@dt@@", dateLabel.text.replace( "[b]", "<b>" ).replace( "[/b]", "</b>" ) + ", " + timeLabel.text.replace( "[b]", "<b>" ).replace( "[/b]", "</b>" ) )
			html = html.replace( "@@heatChecked@@", "checked" if heatControl.state == "down" else "" )
			html = html.replace( "@@coolChecked@@", "checked" if coolControl.state == "down" else "" )
			html = html.replace( "@@fanChecked@@", "checked" if fanControl.state == "down" else "" )
			html = html.replace( "@@holdChecked@@", "checked" if holdControl.state == "down" else "" )
	
		return html


	@cherrypy.expose
	def set( self, temp, heat="off", cool="off", fan="off", hold="off" ):
		global setTemp
		global setLabel
		global heatControl
		global coolControl
		global fanControl

		log( LOG_LEVEL_INFO, CHILD_DEVICE_WEBSERVER, MSG_SUBTYPE_TEXT, "Set thermostat received from: " + cherrypy.request.remote.ip )	

		tempChanged = setTemp != float( temp )

		with thermostatLock:
			setTemp = float( temp )
			setLabel.text = "  Set\n[b]" + str( setTemp ) + "c[/b]"
			tempSlider.value = setTemp

			if tempChanged:
				log( LOG_LEVEL_STATE, CHILD_DEVICE_WEBSERVER, MSG_SUBTYPE_TEMPERATURE, str( setTemp ) )

			if heat == "on":
				setControlState( heatControl, "down" )
			else:
				setControlState( heatControl, "normal" )

			if cool == "on":
				setControlState( coolControl, "down" )
			else:
				setControlState( coolControl, "normal" )

			if fan == "on":
				setControlState( fanControl, "down" )
			else:
				setControlState( fanControl, "normal" )

			if hold == "on":
				setControlState( holdControl, "down" )
			else:
				setControlState( holdControl, "normal" )

			reloadSchedule()

		file = open( "web/html/thermostat_set.html", "r" )

		html = file.read()

		file.close()
		
		with thermostatLock:
			html = html.replace( "@@version@@", str( THERMOSTAT_VERSION ) )
			html = html.replace( "@@dt@@", dateLabel.text.replace( "[b]", "<b>" ).replace( "[/b]", "</b>" ) + ", " + timeLabel.text.replace( "[b]", "<b>" ).replace( "[/b]", "</b>" ) )
			html = html.replace( "@@temp@@", ( '<font color="red"><b>' if tempChanged else "" ) + str( setTemp ) + ( '</b></font>' if tempChanged else "" ) )
			html = html.replace( "@@heat@@", ( '<font color="red"><b>' if heat == "on" else "" ) + heat + ( '</b></font>' if heat == "on" else "" ) )
			html = html.replace( "@@cool@@", ( '<font color="red"><b>' if cool == "on" else "" ) + cool + ( '</b></font>' if cool == "on" else "" ) )
			html = html.replace( "@@fan@@",  ( '<font color="red"><b>' if fan == "on" else "" ) + fan + ( '</b></font>' if fan == "on" else "" ) )
			html = html.replace( "@@hold@@", ( '<font color="red"><b>' if hold == "on" else "" ) + hold + ( '</b></font>' if hold == "on" else "" ) )

		return html


	@cherrypy.expose
	def schedule( self ):	
		log( LOG_LEVEL_INFO, CHILD_DEVICE_WEBSERVER, MSG_SUBTYPE_TEXT, "Served thermostat_schedule.html to: " + cherrypy.request.remote.ip )			
		file = open( "web/html/thermostat_schedule.html", "r" )

		html = file.read()

		file.close()
		
		with thermostatLock:
			html = html.replace( "@@version@@", str( THERMOSTAT_VERSION ) )
			html = html.replace( "@@minTemp@@", str( minTemp ) )
			html = html.replace( "@@maxTemp@@", str( maxTemp ) )
			html = html.replace( "@@tempStep@@", str( tempStep ) )
		
			html = html.replace( "@@dt@@", dateLabel.text.replace( "[b]", "<b>" ).replace( "[/b]", "</b>" ) + ", " + timeLabel.text.replace( "[b]", "<b>" ).replace( "[/b]", "</b>" ) )
	
		return html

	@cherrypy.expose
	@cherrypy.tools.json_in()
	def save( self ):
		log( LOG_LEVEL_STATE, CHILD_DEVICE_WEBSERVER, MSG_SUBTYPE_TEXT, "Set schedule received from: " + cherrypy.request.remote.ip )	
		schedule = cherrypy.request.json

		with scheduleLock:
			file = open( "thermostat_schedule.json", "w" )

			file.write( json.dumps( schedule, indent = 4 ) )
		
			file.close()

		reloadSchedule()

		file = open( "web/html/thermostat_saved.html", "r" )

		html = file.read()

		file.close()
		
		with thermostatLock:
			html = html.replace( "@@version@@", str( THERMOSTAT_VERSION ) )
			html = html.replace( "@@dt@@", dateLabel.text.replace( "[b]", "<b>" ).replace( "[/b]", "</b>" ) + ", " + timeLabel.text.replace( "[b]", "<b>" ).replace( "[/b]", "</b>" ) )
		
		return html


def startWebServer():	
	host = "discover" if not( settings.exists( "web" ) ) else settings.get( "web" )[ "host" ]
	cherrypy.server.socket_host = host if host != "discover" else get_ip_address()								# use machine IP address if host = "discover"
	cherrypy.server.socket_port = 80 if not( settings.exists( "web" ) ) else settings.get( "web" )[ "port" ]

	log( LOG_LEVEL_STATE, CHILD_DEVICE_WEBSERVER, MSG_SUBTYPE_TEXT, "Starting on " + cherrypy.server.socket_host + ":" + str( cherrypy.server.socket_port ) )

	conf = {
		'/': {
			'tools.staticdir.root': os.path.abspath( os.getcwd() ),
			'tools.staticfile.root': os.path.abspath( os.getcwd() )
		},
		'/css': {
			'tools.staticdir.on': True,
			'tools.staticdir.dir': './web/css'
		},
		'/javascript': {
			'tools.staticdir.on': True,
			'tools.staticdir.dir': './web/javascript'
		},
		'/images': {
			'tools.staticdir.on': True,
			'tools.staticdir.dir': './web/images'
		},
		'/schedule.json': {
			'tools.staticfile.on': True,
			'tools.staticfile.filename': './thermostat_schedule.json'
		},
		'/favicon.ico': {
			'tools.staticfile.on': True,
			'tools.staticfile.filename': './web/images/favicon.ico'
		}

	}

	cherrypy.config.update(
		{ 'log.screen': debug,
		  'log.access_file': "",
		  'log.error_file': ""
		}
	)

	cherrypy.quickstart ( WebInterface(), '/', conf )	


##############################################################################
#                                                                            #
#       Main                                                                 #
#                                                                            #
##############################################################################

def main():
	# Start Web Server
	webThread = threading.Thread( target=startWebServer )
	webThread.daemon = True
	webThread.start()

	# Start Scheduler
	reloadSchedule()
	schedThread = threading.Thread( target=startScheduler )
	schedThread.daemon = True
	schedThread.start()

	# Start Thermostat UI/App
	ThermostatApp().run()


if __name__ == '__main__':
	try:
		main()
	finally:
		log( LOG_LEVEL_STATE, CHILD_DEVICE_NODE, MSG_SUBTYPE_CUSTOM + "/shutdown", "Thermostat Shutting Down..." )
		GPIO.cleanup()

		if logFile is not None:
			logFile.flush()
			os.fsync( logFile.fileno() )
			logFile.close()

		if mqttEnabled:	
			mqttc.loop_stop()
			mqttc.disconnect()

