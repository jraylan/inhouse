# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os

# This is defined here as a do-nothing function because we can't import
# django.utils.translation -- that module depends on the settings.
def gettext_noop(s):
    return s


####################
# CORE             #
####################

DEBUG = True
TIME_ZONE = 'America/Fortaleza'

# If you set this to True, Django will use timezone-aware datetimes.
USE_TZ = True

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = 'pt-br'
DATABASES = {
    'default': {
        #"ENGINE": "psqlextra.backend",
        'ENGINE':   'django.db.backends.postgresql_psycopg2',
        'NAME':     os.environ["INHOUSE_DB_NAME"],
        'USER':     os.environ["INHOUSE_DB_USER"],
        'PASSWORD': os.environ["INHOUSE_DB_PASSOWRD"],
        'HOST':     os.environ["INHOUSE_DB_HOST"],
        'PORT':     os.environ["INHOUSE_DB_PORT"],
    },

}

# List of strings representing installed apps.
INSTALLED_APPS = [
    'inhouse',
    #'psqlextra',

]

MIDDLEWARE_CLASSES = []


# Make this unique, and don't share it with anybody.
SECRET_KEY = 'hlq$($u)lsof=3f4547)sf@a%d%6n!b7r+m!=2x+1cu5mw762m'

import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

sentry_sdk.init(
    dsn="https://b3c666e60e7b4aac9b7fc2dcfeb06c82@o500709.ingest.sentry.io/5580943",
    integrations=[DjangoIntegration()],

    # Set traces_sample_rate to 1.0 to capture 100%
    # of transactions for performance monitoring.
    # We recommend adjusting this value in production,
    traces_sample_rate=1.0,

    # If you wish to associate users to errors (assuming you are using
    # django.contrib.auth) you may enable sending PII data.
    send_default_pii=True
)