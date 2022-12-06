import datetime
import logging
import os
import json

import requests

from flask import Flask, session, request, render_template, make_response, redirect, url_for

# different buckets for dev vs. production
from google.cloud import storage
from google.cloud import ndb

from web.site import site

import config

if __name__ == '__main__':
	# This is used when running locally. Gunicorn is used to run the
	# application on Google App Engine. See entrypoint in app.yaml.
	# app.run(host='127.0.0.1', port=8080, debug=True)
	app.run(host='0.0.0.0', port=8080, debug=True)
	dev = True
