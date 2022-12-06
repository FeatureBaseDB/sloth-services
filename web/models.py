import datetime
import os
import requests
import json
import random

from google.cloud import ndb, storage

import flask_login

from lib.util import random_string, random_number, generate_token, random_name, find_urls
from lib.solr import create_core

import config

# models.py - data structure models
# see model.py for machine learning model methods

# client connection
client = ndb.Client()

timestring = "%Y-%m-%dT%H:%M:%SZ"

# in general, the stuff we keep long term includes users, folders created on cloud storage (spools), 

# transactions secure queries
class Transaction(ndb.Model):
	uid = ndb.StringProperty() # owner
	tid = ndb.StringProperty()
	created = ndb.DateTimeProperty()

	@classmethod
	def get_old(cls, timestamp):
		with client.context():
			return cls.query(cls.created < timestamp)

	@classmethod
	def get_by_tid(cls, tid):
		with client.context():
			return cls.query(cls.tid == tid).get()

	@classmethod
	def create(cls, tid=None, uid=None):
		with client.context():
			cls(
				tid = tid,
				uid = uid,
				created = datetime.datetime.utcnow()
			).put()
			return cls.query(cls.tid == tid).get()


class Events(ndb.Model):
	created = ndb.DateTimeProperty()
	eid = ndb.StringProperty() # event ID
	uid = ndb.StringProperty() # user ID
	pipe = ndb.StringProperty() # pipeline name
	entity = ndb.StringProperty() # useful string
	text = ndb.StringProperty() # text of the event

	@classmethod
	def pop_by_uid_pipe(cls, uid, pipe):
		with client.context():
			# delete any events older than one minute
			events = cls.query().filter().order(cls.created).fetch()
			for event in events:
				earlier = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)

				if event.created < earlier:
					event.key.delete()

			event = cls.query(cls.uid==uid, cls.pipe==pipe).filter().order(cls.created).get()

			if event:
				event_text = event.text
				event_entity = event.entity
				event_pipe = event.pipe
				event.key.delete() # pop the event off the stack
				return {"pipe": event_pipe, "entity": event_entity, "text": event_text}
			else:
				return None

	@classmethod
	def pop_by_uid_pipe_entity(cls, uid, pipe, entity):
		with client.context():
			# delete any events older than one minute
			events = cls.query().filter().order(cls.created).fetch()
			for event in events:
				earlier = datetime.datetime.utcnow() - datetime.timedelta(minutes=1)

				if event.created < earlier:
					event.key.delete()

			event = cls.query(cls.uid==uid, cls.pipe==pipe, cls.entity==entity).filter().order(cls.created).get()

			if event:
				event_text = event.text
				event_entity = event.entity
				event_pipe = event.pipe
				event.key.delete() # pop the event off the stack
				return {"pipe": event_pipe, "entity": event_entity, "text": event_text}
			else:
				return None

	@classmethod
	def create(cls, uid=None, pipe=None, entity=None, text=None):
		eid = random_string(17)
		with client.context():
			cls(
				created = datetime.datetime.utcnow(),
				eid = eid,
				uid = uid,
				pipe = pipe,
				entity = entity,
				text = text
			).put()
			event = cls.query(cls.eid == eid).get().to_dict()
			event['created'] = "1" # they don't need when it was created
			return event

# track slack events, sigh
# TODO cleanup job
class Slack_Event(ndb.Model):
	created = ndb.DateTimeProperty()
	event_time = ndb.IntegerProperty()
	event_id = ndb.StringProperty()

	@classmethod
	def get_by_event_id(cls, event_id):
		with client.context():
			return cls.query(cls.event_id == event_id).get()

	@classmethod
	def create(cls, event_time=None, event_id=None):
		with client.context():
			cls(
				event_time = event_time,
				event_id = event_id,
				created = datetime.datetime.utcnow()
			).put()

			return cls.query(cls.event_id == event_id).get()

# user inherits from flask_login and ndb
class Waitlist(ndb.Model):
	name = ndb.StringProperty() # name
	email = ndb.StringProperty() # email
	allow = ndb.BooleanProperty() # allow to signup
	created = ndb.DateTimeProperty()

	@classmethod
	def create(cls, email="noreply@mitta.us", name="jigmund"):
		with client.context():
			cls(
				name = name,
				email = email,
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


# user inherits from flask_login and ndb
class User(flask_login.UserMixin, ndb.Model):
	uid = ndb.StringProperty() # user_id
	name = ndb.StringProperty() # assigned name
	created = ndb.DateTimeProperty()
	updated = ndb.DateTimeProperty()
	expires = ndb.DateTimeProperty()
	admin = ndb.BooleanProperty() # may create command sidekicks

	# auth settings and log
	email = ndb.StringProperty()
	phone = ndb.StringProperty()
	phone_code = ndb.StringProperty(default=False)
	failed_2fa_attempts = ndb.IntegerProperty(default=0)

	# email actions
	mail_token = ndb.StringProperty()
	mail_confirm = ndb.BooleanProperty(default=False)
	mail_tries = ndb.IntegerProperty(default=0)

	# status
	authenticated = ndb.BooleanProperty(default=False)
	active = ndb.BooleanProperty(default=True)
	anonymous = ndb.BooleanProperty(default=False)
	paid = ndb.BooleanProperty(default=False)
	account_type = ndb.StringProperty(default="free")

	# slack settings
	slack_id = ndb.StringProperty()
	slack_teamID = ndb.StringProperty()
	slack_access_token = ndb.StringProperty()

	# API use
	api_token = ndb.StringProperty()

	# flask-login
	def is_active(self): # all accounts are active
		return self.active

	def get_id(self):
		return self.uid

	def is_admin(self):
		return self.admin

	def is_authenticated(self):
		return self.authenticated

	def is_anonymous(self):
		return self.anonymous

	def has_phone(self):
		if self.phone != "+1":
			return True
		return False

	@classmethod
	def token_reset(cls, uid=uid):
		with client.context():
			user = cls.query(cls.uid == uid).get()
			user.api_token = generate_token()
			user.put()
			return user

	@classmethod
	def create(cls, email="noreply@mitta.us", phone="+1"):
		name = random_name(3)
		uid = random_string(size=17)
		with client.context():
			cls(
				uid = uid,
				name = name,
				email = email,
				account_type = "free",
				phone = phone,
				phone_code = generate_token(),
				created = datetime.datetime.utcnow(),
				updated = datetime.datetime.utcnow(),
				expires = datetime.datetime.utcnow() + datetime.timedelta(days=15),
				admin = False,
				mail_token = generate_token(),
				api_token = generate_token()
			).put()

			return cls.query(cls.phone == phone, cls.email == email).get()

	@classmethod
	def get_old(cls, timestamp):
		with client.context():
			# return cls.query(cls.updated < timestamp).fetch(10000)
			return cls.query(cls.updated < timestamp).fetch(10000)

	@classmethod
	def get_all_for_tasks(cls):
		with client.context():
			# return cls.query(cls.updated < timestamp).fetch(10000)
			return cls.query().fetch(10000)

	@classmethod
	def get_by_name(cls, name):
		with client.context():
			return cls.query(cls.name == name).get()

	@classmethod
	def get_by_slack_id_team(cls, slack_id, slack_teamID):
		with client.context():
			return cls.query(cls.slack_id == slack_id, cls.slack_teamID == slack_teamID).get()

	@classmethod
	def get_by_email(cls, email):
		with client.context():
			return cls.query(cls.email == email).get()

	@classmethod
	def get_by_phone(cls, phone):
		with client.context():
			return cls.query(cls.phone == phone).get()

	@classmethod
	def get_by_mail_token(cls, mail_token):
		with client.context():
			return cls.query(cls.mail_token == mail_token).get()

	@classmethod
	def get_by_uid(cls, uid):
		with client.context():
			return cls.query(cls.uid == uid).get()

	@classmethod
	def get_by_token(cls, api_token):
		with client.context():
			return cls.query(cls.api_token == api_token).get()


# user settings
class Settings(ndb.Model):
	uid = ndb.StringProperty() # user
	name = ndb.StringProperty() # name
	value = ndb.JsonProperty() # value or json object
	updated = ndb.DateTimeProperty()

	@classmethod
	def create(cls, uid=None, name="var1", value=[], methods=['GET','POST']):

		# check for setting already being set
		with client.context():
			query = cls.query(cls.name == name, cls.uid == uid)
			setting = query.get()
			if setting:
				return setting

		# create a new one
		with client.context():
			cls(
				uid = uid,
				name = name,
				value = value,
				updated = datetime.datetime.utcnow()
			).put()

			return cls.query(cls.uid == uid, cls.name == name).get()

	@classmethod
	def get_by_uid_name(cls, uid, name):
		with client.context():
			return cls.query(cls.uid == uid, cls.name == name).get()

	@classmethod
	def get_all(cls, uid):
		with client.context():
			return cls.query(cls.uid == uid).fetch(10) # needs to be set in config.py TODO


# cloud storage directory for images or screenshots
# sort of like an album, with a name, title and some tags
class Spool(ndb.Model):
	# identity
	uid = ndb.StringProperty() # user or owner
	name = ndb.StringProperty() # reference name
	public = ndb.BooleanProperty(default=False)
	
	# timestamps
	created = ndb.DateTimeProperty()
	updated = ndb.DateTimeProperty()
	expires = ndb.DateTimeProperty()

	# status
	nick = ndb.StringProperty() # user friendly name
	title = ndb.StringProperty() # title

	# hostname
	fq_domain = ndb.StringProperty()

	# insecure
	@classmethod
	def get_by_nick(cls, nick):
		with client.context():
			return cls.query(cls.nick == nick, cls.public == True).get()

	# secured use only (i.e. from authenticated calls only)
	@classmethod
	def get_by_nick_private(cls, nick):
		with client.context():
			return cls.query(cls.nick == nick, cls.public == False).get()

	@classmethod
	def get_by_name(cls, name):
		with client.context():
			return cls.query(cls.name == name).get()

	@classmethod
	def get_by_name_public(cls, name):
		with client.context():
			return cls.query(cls.name == name, cls.public == True).get()

	@classmethod
	def get_all_for_tasks(cls):
		with client.context():
			return cls.query().fetch(10000)

	# secure
	# get any private spools
	@classmethod
	def get_all(cls, uid):
		with client.context():
			return cls.query(cls.uid == uid, cls.public == False).fetch()

	@classmethod
	def get_by_fq_domain(cls, fq_domain):
		with client.context():
			return cls.query(cls.fq_domain == fq_domain).get()

	@classmethod 
	def get_by_uid_name(cls, uid, name):
		with client.context():
			return cls.query(cls.uid == uid, cls.name == name).get()

	@classmethod
	def get_by_uid_url(cls, uid, url):
		with client.context():
			return cls.query(cls.uid == uid, cls.url == url).get()

	@classmethod
	def get_by_uid_nick(cls, uid, nick):
		with client.context():
			query = cls.query(cls.uid == uid, cls.nick == nick).get()
			return query

	@classmethod
	def get_filenames(cls, uid, name):
		spool = Spool.get_by_uid_name(uid, name)
		if not spool:
			return []

		# storage connection
		gcs = storage.Client()

		blobs = gcs.list_blobs(config.cloud_storage_bucket, prefix="%s/%s" %(uid, spool.name))

		filenames = []
		for blob in blobs:
			filename = blob.name.split("%s/%s/" % (uid, spool.name))[1]
			filenames.append({"filename": filename, "updated": "%s" % blob.updated.strftime(timestring)})

		return sorted(filenames, key=lambda field: field['updated'])

	@classmethod
	def get_filecount(cls, uid, nick):
		spool = Spool.get_by_uid_name(uid, name)
		if not spool:
			return []

		# storage connection
		gcs = storage.Client()
		blobs = gcs.list_blobs(config.cloud_storage_bucket, prefix="%s/%s" %(uid, spool.name))

		file_count = 0
		for blob in blobs:
			file_count = file_count + 1

		return file_count

	@classmethod
	def create(
		cls,
		uid = uid,
		title = title,
		fq_domain = fq_domain,
		public = public
	):
		# check for spool with fq_domain
		with client.context():
			# get matching by fq_domain, if it exists
			query = cls.query(cls.fq_domain == fq_domain).filter().order(cls.created)
			spool = query.get()

			if spool:
				if title:
					spool.title = title
				spool.updated = datetime.datetime.utcnow()
				spool.put()

		# if we find a spool, gaurd against returning a public one
		with client.context():
			if spool and spool.public == True:
				return spool
	
		# create new spool names
		name = "spool_%s" % random_string(size=13)
		nick = random_name(3)

		if public == None:
			public = True
		
		# create new spool
		with client.context():
			cls(
				created = datetime.datetime.utcnow(),
				updated = datetime.datetime.utcnow(),
				uid = uid,
				name = name,
				nick = nick,
				title = title[:1000],
				fq_domain = fq_domain,
				public = public
			).put()

			return cls.query(cls.name == name).get()


# sidekicks are search indexes or collections
class Sidekick(ndb.Model):
	created = ndb.DateTimeProperty()
	updated = ndb.DateTimeProperty() # updated time
	started = ndb.DateTimeProperty() # started
	uid = ndb.StringProperty() # creating user
	name = ndb.StringProperty() # name
	title = ndb.StringProperty() # title
	nick = ndb.StringProperty() # nick
	instance_name = ndb.StringProperty() # instance running index
	instance_ip = ndb.StringProperty() # IP address
	region = ndb.StringProperty()
	mood = ndb.StringProperty()
	numDocs = ndb.IntegerProperty(default=0)

	def get_numDocs(self):
		return self.numDocs

	# unsecured
	@classmethod
	def get_by_nick(cls, nick):
		with client.context():
			return cls.query(cls.nick == nick).get()

	# secured
	@classmethod
	def get_all(cls, uid):
		with client.context():
			return cls.query(cls.uid == uid).fetch() # configure limits

	@classmethod
	def get_by_user(cls, uid):
		# get default sidekick setting
		sidekick_setting = Settings.get_by_uid_name(uid, "sidekick")
		sidekick_nick = json.loads(sidekick_setting.value)
		with client.context():
			return cls.query(cls.nick == sidekick_nick).get()

	@classmethod
	def get_by_user_all(cls, uid):
		with client.context():
			return cls.query(cls.uid == uid).fetch(20)

	@classmethod
	def get_by_uid_name(cls, uid, name):
		with client.context():
			return cls.query(cls.uid == uid, cls.name == name).get()

	@classmethod
	def get_by_uid_nick(cls, uid, nick):
		with client.context():
			return cls.query(cls.uid == uid, cls.nick == nick).get()

	@classmethod
	def create(cls, uid=None, title="", user_sidekick=None, user_sidekick_nick=None):
		# new name
		name = "sidekick_%s" % random_string(size=13)
		nick = random_name(2)

		# determine where to put the index
		instance_name = "solr-3xpx"
		instance_ip = "35.230.108.84"
		region = "us-west1-c"
		
		# mood
		mood = random.choice(config.moods)

		# try to create the collection (this can also happen from start() in solr.py)
		create_core(name, instance_ip)

		with client.context():
			cls(
				created = datetime.datetime.utcnow(),
				updated = datetime.datetime.utcnow(),
				started = datetime.datetime.utcnow(),
				uid = uid,
				name = name,
				title = title,
				nick = nick,
				instance_name = instance_name,
				instance_ip = instance_ip,
				region = region,
				numDocs = 0,
				mood = mood
			).put()

			return cls.query(cls.uid == uid, cls.name == name).get()
