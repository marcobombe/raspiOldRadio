#!/usr/bin/env python

# Copyright 2020 Marco Bombelli 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.


# Main part of raspiOldRadio
#
# See install.sh for requirements

import time, syslog, sys, os, mpd, json, RPi.GPIO as GPIO, socket
from datetime import datetime
from threading import Thread
import threading
import configparser
from configparser import ConfigParser
from gpiozero import * 
from os import system, name 
from os import listdir
from os.path import isfile, join
import subprocess

# Global variables
mpdhost = 'localhost'
client = mpd.MPDClient () 

nowVolume = 0
prevVolume = 0
muted = False

debounceCounter = 0
pause = 0
verbose = False

VolClkLastState = 0 
volCnt = 0

prevNextClkLastState = 0 
prevNextCnt = 0 

oneSecTogglingBit = 0;

ColorRedCmd = 'fixOff';
ColorGreenCmd = 'fixOff';
ColorBlueCmd = 'fixOff';

statrupCounter = 0;

def WriteLog (msg, error = False):
	severity = syslog.LOG_INFO
	if error:
		severity = syslog.LOG_ERR
	if verbose:
		print(severity, msg)
	syslog.syslog (severity, msg)


def startupMPDConnection (c):
	reconnectCounter = 0
	blink = 0;
	clientStatus = False;
	while clientStatus == False:
		print("MPD Client try to connect to MPD: tentative number " + str(reconnectCounter) + ", at " + datetime.now().strftime('%d-%m-%Y %H:%M:%S') + ".")
		reconnectCounter += 1
		clientStatus = ConnectMPD (c)
		time.sleep (1)
		GPIO.output(RGB_LED1_BLUE, blink) 
		if blink==0:
			blink = 1;
		elif blink==1:
			blink = 0;	
	
	print("MPD Client connected to MPD (tentative number " + str(reconnectCounter-1) + ", " + datetime.now().strftime('%d-%m-%Y %H:%M:%S') + ").")
	GPIO.output(RGB_LED1_BLUE, 0)
	return True

def ConnectMPD (c):
	try:
		c.connect (mpdhost, 6600)
		print("Connected to MDP version " + str(c.mpd_version) + ".");
	except mpd.ConnectionError():
		return False
	except socket.error:
		return False

	return True


def DisconnectMPD (c):
	try:
		c.close ()
		print("Disconnected from MDP version " + str(c.mpd_version) + ".");
	except mpd.ConnectionError():
		pass


def StopMPD (c):
	WriteLog ("Stopping MPD")
	try:
		c.clear ()
		return True
	except mpd.ConnectionError():
		print("StopMPD: MPD error.")
		return False


def MuteMPD (c):
	global muted, prevVolume, nowVolume
	WriteLog ("Muting MPD.")
	prevVolume = nowVolume
	muted = True
	SetVolumeMPD (c, 0)


def SetVolumeMPD (c, vol):
	global nowVolume
	print ("Set volume to " + str(vol) + ".")
	nowVolume = vol
	try:
		c.setvol(vol)
	except mpd.ConnectionError():
		print("MPD error setting volume.")
		return False
	return True
	
	
def nextMPD (c):
	print ("Next Song")
	try:
		c.next()
	except mpd.ConnectionError():
		print("MPD error setting next song.")
		return False
	return True	

def previousMPD (c):
	print ("Previous Song")
	try:
		c.previous()
	except mpd.ConnectionError():
		print("MPD error setting previous song.")
		return False
	return True	   

# Volume encoder management  
def volume_callback(channel):  
	global VolClkLastState, nowVolume, client, volCnt
	volCnt = int(nowVolume)
	try:
				vol_clkState = GPIO.input(VOL_ENC_CLK)
				if vol_clkState != VolClkLastState:
						vol_dtState = GPIO.input(VOL_ENC_DT)
						if vol_dtState != vol_clkState:
							if volCnt < 100:
								volCnt += 5
								SetVolumeMPD(client, volCnt)
						else:
							if volCnt > 0:
								volCnt -= 5
								SetVolumeMPD(client, volCnt)
				VolClkLastState = vol_clkState
	finally:
				pass

# Prev/Next encoder management  
def prev_next_callback(channel):  
	global prevNextClkLastState, client
	clientStatus = client.status()
	playlistlength = int(clientStatus.get("playlistlength", 0))
	song = int(clientStatus.get("song", 0))
	try:
				pn_clkState = GPIO.input(PREV_NEXT_ENC_CLK)
				if pn_clkState != prevNextClkLastState:
						pn_dtState = GPIO.input(PREV_NEXT_ENC_DT)
						if pn_dtState != pn_clkState:
							if playlistlength > 1: 
								nextMPD(client)														
						else:
 							if playlistlength > 1: 
								if song >= 1:
									previousMPD(client)											
				prevNextClkLastState = pn_clkState
	finally:
				pass

# Play/Pause button management
def sw_callback(channel): 
	global client, debounceCounter, pause, draw
	debounceCounter += 1
	if debounceCounter == 1:        
		if pause == 0:
			pause = 1
			print("Music paused!")
		else: 
			pause = 0
			print("Playing music!")
		client.pause(pause)
		if pause == 1:
			GPIO.output(RGB_LED1_RED, 1)
			GPIO.output(RGB_LED1_GREEN, 0)
		else:
			GPIO.output(RGB_LED1_RED, 0)
			GPIO.output(RGB_LED1_GREEN, 1)				
		debounceCounter = 0
   
# Prev/Next button management
def prev_next_sw_callback(channel):    
	print ("Prev/Next button pressed!") 
	#pass

# Save config Thread
def StartSaveConfThread():
	global prevVolume, nowVolume, client, parser
	threading.Timer(5.0, StartSaveConfThread).start()
	if prevVolume != nowVolume:
		parser.set('last_config', 'volume', str(nowVolume))
		prevVolume = nowVolume
		#print ("New volume saved to config: "+ str(nowVolume))
		with open('/home/pi/raspiOldRadio/raspiOldRadio.ini', 'w') as configfile:
			parser.write(configfile)

def mng_toggle_bit():
	global oneSecTogglingBit
	if oneSecTogglingBit==0:
		oneSecTogglingBit = 1;
	elif oneSecTogglingBit==1:
		oneSecTogglingBit = 0;	
			
# Periodically ping server Thread
def StartMDPThread():
	global client, oneSecTogglingBit
	threading.Timer(1.0, StartMDPThread).start()
	mng_toggle_bit()
	try:
		print_stats() 
		client.ping()
	except KeyboardInterrupt:
		print("Shutting down cleanly ... (Ctrl + C)")
		sys.exit(0)
	except socket.error:
		GPIO.output(RGB_LED1_GREEN, 0) 
		print("mpd.ConnectionError: MPD stopped. Reconnecting3.")
		ConnectMPD (client) 
	except mpd.ConnectionError:
		GPIO.output(RGB_LED1_GREEN, 0) 
		print("mpd.ConnectionError: MPD stopped. Reconnecting2.")
		ConnectMPD (client) 
 
def print_stats():
	global oneSecTogglingBit, ColorRedCmd, ColorGreenCmd, ColorBlueCmd, client, statrupCounter
	
	clientStatus = client.status()
	elapsedTime = str(clientStatus.get("time", 0))
	volume = str(clientStatus.get("volume", 0))
	state = str(clientStatus.get("state", 0))
	songid = str(clientStatus.get("songid", 0))
	song = str(clientStatus.get("song", 0))
	single = str(clientStatus.get("single", 0))
	repeat = str(clientStatus.get("repeat", 0))
	random = str(clientStatus.get("random", 0))
	playlist = str(clientStatus.get("playlist", 0))
	playlistlength = str(clientStatus.get("playlistlength", 0))
	mixrampdb = str(clientStatus.get("mixrampdb", 0))
	elapsed = str(clientStatus.get("elapsed", 0))
	consume = str(clientStatus.get("consume", 0))	
	bitrate = str(clientStatus.get("bitrate", 0))	
	audio = str(clientStatus.get("audio", 0))	
	albums = str(clientStatus.get("albums", 0))
	artists = str(clientStatus.get("artists", 0))
	db_playtime = str(clientStatus.get("db_playtime", 0))
	db_update = str(clientStatus.get("db_update", 0))
	playtime = str(clientStatus.get("playtime", 0))
	songs = str(clientStatus.get("songs", 0))
	uptime = str(clientStatus.get("uptime", 0))	

	print('\nCurrent MPD state:')
	print ("TIME: " + elapsedTime + " STATE: " + state +  " VOL: " + volume)
	print ("SONG: " + song + " SONGID: " + songid)
	print ("SINGLE: " + single + " REPEAT: " + repeat + " RANDOM: " + random)
	print ("PLYLIST: " + playlist + " PLYLISTLEN: " + playlistlength)
	print ("MIXRAMPDB: " + mixrampdb + " ELAPSED: " + elapsed)
	print ("CONSUME: " + consume)
	print ("BITRATE: " + bitrate + " AUDIO: " + audio)

	print('\nMusic Library stats:')
	print ("ALBUMS: " + albums + " ARTISTS: " + artists + " DB_PLAYTIME: " + db_playtime)
	print ("DB_UPDATE: " + db_update + " PLAYTIME: " + playtime + " SONGS: " + songs)
	print ("UPTIME: " + uptime)
	print ("TOGGLE:  " + str (oneSecTogglingBit) + " LEDRED: " + str (ColorRedCmd) + " LEDGREEN: " + str (ColorGreenCmd) + " LEDBLUE: " + str (ColorBlueCmd))
	print ("STRUPCNT: " + str(statrupCounter))

	# Set the leds behaviour accordingly respect mpd statuscolor_red_cmd
	if state == "play":
		ColorRedCmd = 'fixOff'
		ColorGreenCmd = 'blink'
		ColorBlueCmd = 'fixOff'
	elif state =="pause":
		ColorRedCmd = 'fixOn'
		ColorGreenCmd = 'fixOff'
		ColorBlueCmd = 'fixOff'

	# Simple WorkAround when still connected but elapsed time stall to 0:0
	statrupCounter = statrupCounter + 1;
	if statrupCounter > 5:	
		if (audio == "0"):		
			print "Audio is ZERO. DISCONNECT!"
			DisconnectMPD(client)
			statrupCounter = 0;

def ledMngWorker():
	global ColorRedCmd, ColorGreenCmd, ColorBlueCmd, oneSecTogglingBit, client;
	if ColorRedCmd == 'fixOn':
		GPIO.output(RGB_LED1_RED, 1) 
	elif ColorRedCmd == 'fixOff':
		GPIO.output(RGB_LED1_RED, 0) 
	elif ColorRedCmd == 'blink':
		GPIO.output(RGB_LED1_RED, oneSecTogglingBit) 

	if ColorGreenCmd == 'fixOn':
		GPIO.output(RGB_LED1_GREEN, 1) 
	elif ColorGreenCmd == 'fixOff':
		GPIO.output(RGB_LED1_GREEN, 0) 
	elif ColorGreenCmd == 'blink':
		GPIO.output(RGB_LED1_GREEN, oneSecTogglingBit) 

	if ColorBlueCmd == 'fixOn':
		GPIO.output(RGB_LED1_BLUE, 1) 
	elif ColorBlueCmd == 'fixOff':
		GPIO.output(RGB_LED1_BLUE, 0) 
	elif ColorBlueCmd == 'blink':
		GPIO.output(RGB_LED1_BLUE, oneSecTogglingBit) 	

# RGB Led 1
RGB_LED1_GREEN = 13
RGB_LED1_RED = 6
RGB_LED1_BLUE = 5
# Volume encoder
VOL_ENC_CLK = 17
VOL_ENC_DT = 18
VOL_ENC_SW = 27
# Prev/Next encoder
PREV_NEXT_ENC_CLK = 21
PREV_NEXT_ENC_DT = 20
PREV_NEXT_ENC_SW = 16
GPIO.setwarnings(False) 
# Set GPIO Board Notation
GPIO.setmode(GPIO.BCM)
# Setup Led 1 pins
GPIO.setup(RGB_LED1_RED, GPIO.OUT)
GPIO.setup(RGB_LED1_GREEN, GPIO.OUT)
GPIO.setup(RGB_LED1_BLUE, GPIO.OUT)
# Setup Volume encoder pins
GPIO.setup(VOL_ENC_CLK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(VOL_ENC_DT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(VOL_ENC_SW, GPIO.IN, pull_up_down=GPIO.PUD_UP)
# Setup Prev/Next encoder pins
GPIO.setup(PREV_NEXT_ENC_CLK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(PREV_NEXT_ENC_DT, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(PREV_NEXT_ENC_SW, GPIO.IN, pull_up_down=GPIO.PUD_UP)

#shutdown button
stopButton = Button(12)

# Hardware init
VolClkLastState = GPIO.input(VOL_ENC_CLK)
GPIO.add_event_detect(VOL_ENC_CLK, GPIO.FALLING  , callback=volume_callback, bouncetime=1) 
GPIO.add_event_detect(VOL_ENC_SW, GPIO.FALLING , callback=sw_callback, bouncetime=300)  
VolClkLastState = GPIO.input(VOL_ENC_CLK)

prevNextClkLastState = GPIO.input(PREV_NEXT_ENC_CLK)
GPIO.add_event_detect(PREV_NEXT_ENC_CLK, GPIO.FALLING  , callback=prev_next_callback, bouncetime=1) 
GPIO.add_event_detect(PREV_NEXT_ENC_SW, GPIO.FALLING , callback=prev_next_sw_callback, bouncetime=300)  
prevNextClkLastState = GPIO.input(PREV_NEXT_ENC_CLK)

def InitMPDConnection():
	global client
	# Print out MPD start stats
	print("#########################################################################################")
	print("  ")
	print ("raspiOldRadio started at: " + datetime.now().strftime('%d-%m-%Y %H:%M:%S') + ".")
	startupMPDConnection (client)
	StopMPD (client)
	print("  ")
	print("#########################################################################################")
	print("  ")

def StartupConfigRestore():
	global parser, nowVolume, prevVolume, client
	# Restore last configuration saved
	print ("PysicalRadio initial configuration")
	parser = ConfigParser()
	parser.read('/home/pi/raspiOldRadio/raspiOldRadio.ini')
	nowVolume = parser.get('last_config', 'volume');
	prevVolume = nowVolume;
	print ("Config volume is " + str(nowVolume))
	SetVolumeMPD(client, nowVolume)

def AddRadioDjToPlaylist():
	global client
	# Always add to playlist Radio Deejay
	radio_deejay_position = client.addid("http://radiodeejay-lh.akamaihd.net/i/RadioDeejay_Live_1@189857/master.m3u8")
	print ("Added Radio Deejay to playlist (" + str(radio_deejay_position)+ ").") 
	time.sleep (1)
	client.play(0)
	print("Playing music!")
	print("  ")
	print("#########################################################################################")
	print("  ")
	
def clearLeds():
	global RGB_LED1_RED, RGB_LED1_GREEN, RGB_LED1_BLUE
	GPIO.output(RGB_LED1_RED, 0) 
	GPIO.output(RGB_LED1_GREEN, 0) 
	GPIO.output(RGB_LED1_BLUE, 0) 
	
def shutDownDevice():
	print("Shutting down the radio...")
	os.system("sudo shutdown now -h")	
	
clearLeds()	
InitMPDConnection()	
StartupConfigRestore()
AddRadioDjToPlaylist()

# Start Threads
StartMDPThread() 
StartSaveConfThread() 

# Main loopsave_config
while True:
	try:
		
		time.sleep (0.01)
		
		if stopButton.is_pressed: 
			shutDownDevice()
		
		ledMngWorker()
			
	except KeyboardInterrupt:
		print("Shutting down cleanly ... (Ctrl + C)")
		clearLeds()
		sys.exit(0)
	except socket.error:
		print("socket.error MPD stopped?")
		clearLeds()
	except mpd.ConnectionError:
		print("mpd.ConnectionError: MPD stopped. Reconnecting1.")
		clearLeds()
		DisconnectMPD (client)
		time.sleep(1)
		InitMPDConnection()	
		StartupConfigRestore()
		AddRadioDjToPlaylist()
