import datetime
import os
import requests
import json
import random

from google.cloud import ndb, storage

from lib.util import random_string, random_number, generate_token, random_name, find_urls

import config

# client connection
client = ndb.Client()

timestring = "%Y-%m-%dT%H:%M:%SZ"

# user inherits from flask_login and ndb
class Version(ndb.Model):
	name = ndb.StringProperty() # name
	allow = ndb.BooleanProperty() # allow to signup
	created = ndb.DateTimeProperty()

	@classmethod
	def create(cls, email="noreply@mitta.us", name="jigmund"):
		with client.context():
			cls(
				name = name,
				allow = False,
				created = datetime.datetime.utcnow()
			).put()

			return cls.query(cls.email == email).get()

	@classmethod
	def get_all(cls):
		with client.context():
			# return cls.query(cls.updated < timestamp).fetch(10000)
			return cls.query().fetch(200)

	@classmethod
	def get_allowed_by_email(cls, email):
		with client.context():
			return cls.query(cls.email == email, cls.allow == True).get()

	@classmethod
	def get_by_email(cls, email):
		with client.context():
			return cls.query(cls.email == email).get()