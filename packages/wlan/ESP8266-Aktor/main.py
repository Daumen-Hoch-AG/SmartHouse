#!/usr/bin/python3
# -*- coding: utf-8 -*-	

####################################################
# Interrupt-Handler müssen:
#
#	- interrupted mit einer Liste wie folgt belegen:
# 	  [str(Funktionsname), kwargs**]
#	- timeout > 0 setzen
#
# Benötigte Funktionen:
#	- hoch/runter rollen
#	- Stoppen
#	- Unpair auslösen und bestätigen
#
####################################################

try:
	import uhashlib as hashlib
	import ubinascii
	from ubinascii import hexlify
	import usocket as socket
	import uselect as select
	import utime as time
except ImportError:
	import hashlib
	import binascii
	from binascii import hexlify
	import socket
	import select
	import time


# Config und Vars
CONFIG_FILE = "main_config.cfg"
try:
	with open(CONFIG_FILE) as c:
		print("Lade persistent Config")
		PAIR = c.readline().strip()
		if PAIR != "" and PAIR != "DEFAULTS":
			ID = int(c.readline().strip())
			SALT = c.readline().strip()
			SEP = c.readline().strip().encode()
		else:
			raise OSError
except OSError:
	print("Keine Config oder Pairing vorhanden (Default)")
	PAIR = False
	ID = 0
	SALT = str(ID)
	SEP = b"%%%"

print("> Config:", "PAIR ID SALT SEP")
print(PAIR, ID, SALT, SEP)



class Listener:
	def __init__(self, ip="0.0.0.0", port=8080):
		# von der Klasse editierbare Settings
		self.PAIR = PAIR
		self.ID = ID
		self.SALT = SALT
		self.actions = {}
		# Flags
		self.timer = 0
		self.timeout = None
		self.running = False
		self.interrupted = False
		self.cache = ""

		# Create Socket
		addr = socket.getaddrinfo(ip, port)[0][-1]
		self.server = socket.socket()
		self.server.setblocking(0)
		self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		self.server.bind(addr)
		self.server.listen(5)

		# Handled Lists
		self.inputs = [self.server]
		self.outputs = []
		self.errors = []

		# Security: Link Funktionen zu Hash
		self.generateHashes()

		print("\n> ESP bereit")


	def run(self):
		print("\n> Listening...\n")

		while True:

			# > Handle Flags
			if self.interrupted:
				# Es gab einen Interrupt
				print("Interrupted ! ---", self.interrupted[0])
				# - Funktionsaufruf anhand Name
				self.getattr(self.interrupted[0])(self.interrupted[1:])
				self.interrupted = False

			elif self.running:
				# Eine Aktion läuft noch
				toWait = self.timer-time.time()
				if toWait > 0:
					print(">", self.running, "noch", round(toWait, 1), "Sek.", end="\r")
				else:
					# Aktion beenden
					self.stopAction()
					print("\n- Gestoppt !")

			else:
				# Normal-Mode
				self.timeout = None
				self.timer = 0

			# Warten bis eine Liste aktiv wird
			readable, writable, exceptional = select.select(self.inputs, self.outputs, self.errors, self.timeout)

			if readable or writable or exceptional:
				# > Inputs
				for sock in readable:
					if sock is self.server:
						# neue eingehende Verbindung
						r = self.accept_new_connection()
						if r:
							print("Client", r[0], ":", r[1], "connected")

					else:
						# bestehende Verbindung sendet
						try:
							# versuche zu Empfangen
							data = sock.recv(1024)
							if data:
								# Input parsen
								print("...processing...")
								try:
									req = data.split(SEP)
									req = list(map(lambda x: x.strip().decode(), req))
									msg = self.actions[req[0]](req[1:])
								except Exception as e:
									print(e.__class__.__name__, ":", e)
									msg = b"keine action\n"
								sock.send(msg)
							else:
								raise Exception
						except Exception:
							# Hier kommt nichts mehr, Verbindung schließen
							print("Connection closed:", sock)
							sock.close()
							self.inputs.remove(sock)

			else:
				# > Loop
				continue


	def generateHashes(self):
		print("\n> Hashes:")
		self.action_names = ["pair", "unpair", "roll", "rollstatus"]
		action_funcs = [self.pair, self.unpair, self.roll, self.rollstatus]
		self.actions = {}
		for act in range(len(self.action_names)):
			newKey = hashlib.sha256(str.encode(self.action_names[act]+self.SALT)).digest()
			newKey = hexlify(newKey).decode()
			self.actions[newKey] = action_funcs[act]
			print(newKey, "\t", self.action_names[act])


	def accept_new_connection(self):
		newsock, (remhost, remport) = self.server.accept()
		if remhost == PAIR or not PAIR:
			self.inputs.append(newsock)
			newsock.send(b"connected\n")
			return (remhost, remport)
		else:
			return False


	def flushConf(self):
		"""Momentane CONFIG (ueber)schreiben"""
		with open(CONFIG_FILE, "w+") as c:
			if not self.PAIR:
				c.write(self.cache)
			else:
				c.write(self.PAIR)
				c.write("\n")
				c.write(self.ID)
				c.write("\n")
				c.write(self.SALT)
				c.write("\n")
				c.write(SEP.decode())
				c.write("\n")
		self.generateHashes()


	def stopAction(self):
		"""Stoppt Bewegung und resettet Timer"""
		if self.running == "roll":
			# <Stoppen triggern/schalten>
			pass
		elif self.running == "unpair":
			# Unpairing verlassen
			self.flushConf()
		self.running = False
		return


	def pair(self, data):
		"""Aktor an eine Node binden (persistent)"""
		try:
			newPair, newID = data[0:2]
			self.PAIR = newPair
			self.ID = newID
			self.SALT = newID
			self.flushConf()
			print("+ pairing: erfolgreich gepaired zu", newPair, "ID:", newID)
			return b"erfolgreich gepaired zu "+str.encode(newPair)+b" ID: "+str.encode(newID)+b"\n"
		except Exception:
			print("- pairing: falsche Angabe von Argumenten")
			return b"falsche Angabe von Argumenten\n"


	def unpair(self):
		"""Temporäres Lösen des Pairings für X Sekunden"""
		with open(CONFIG_FILE, "r") as c:
			# Caching
			self.cache = c.read()
		with open(CONFIG_FILE, "w") as c:
			# Löschen
			c.write("")
		# Mit leerer Config auf Stromtrennung warten
		# Ggf. hier besser etwas mit Schalterinput
		# statt Stromtrennung
		self.timer = time.time()+30
		self.running = "unpair"
		self.timeout = 1
		print("+ unpair: warte 30 Seks mit leerer Config....\n")
		return b"Warte 30 Seks mit leerer Config....\n"


	def roll(self, data):
		"""Rolladen in eine Richtung bewegen"""
		try:
			direction, duration = data[0:2]
			# <Rollen triggern/schalten>
			self.timer = time.time()+int(duration)
			self.running = "roll"
			self.timeout = 0.3
			print("+ rollen nach", direction, "fuer", duration, "s")
			return b"Rolle nach "+str.encode(direction)+b" fuer "+str.encode(duration)+b" Sekunden\n"
		except Exception:
			print("- falsche Angabe von Argumenten")
			return b"falsche Angabe von Argumenten\n"


	def rollstatus(self):
		"""Position des Rolladens wiedergeben"""
		print("+ rollstatus")
		return b"Der Rolladen steht gereade irgendwo...\n"


if __name__ == '__main__':
	server = Listener()
	server.run()