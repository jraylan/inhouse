# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand, CommandError
import sys, os
import re
from inhouse.robot import InhouseBot
import logging
from django.utils import autoreload


class Command(BaseCommand):

    help = 'Inhouse Bot'

    def get_logger_level(self, level):
        if level and level in 'CRITICAL|ERROR|WARNING|INFO|DEBUG'.split('|'):
            return eval(f'logging.{level}')
        return logging.INFO

    def add_arguments(self, parser):
        parser.add_argument('--role',
                dest='role',
                default='',
                help='Se definido, o robô irá executar somente a função determinada. Uso: --role=QUEUE ou --hole=RANKING')
        parser.add_argument('--log-level',
                dest='loglevel',
                default=False,
                help='Define a profundidade do log. Uso --log-level=(CRITICAL|ERROR|WARNING|INFO|DEBUG)')

        parser.add_argument(
            '--reload', action='store_true', dest='use_reloader',
            help='Auto carrega alterações no código (para debug)',
        )

    def handle(self, *args, **options):
        if sys.version_info < (3,0):
            reload(sys)
            sys.setdefaultencoding('utf-8')

        use_reloader = options['use_reloader']

        if use_reloader:
            autoreload.run_with_reloader(self.inner_run, **options)
        else:
            self.inner_run(**options)
    
    def inner_run(self, **options):

        role = options.get('role').upper()

        if role and role not in ['QUEUE', 'RANKING']:
            raise CommandError('"%s" não é uma role válida. Utilize QUEUE ou RANKING.' % role)

        loglevel = self.get_logger_level(options.get('loglevel'))

        root = logging.getLogger()
        root.setLevel(loglevel)
        
        logging.basicConfig(format='%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s',datefmt='%Y-%m-%d:%H:%M:%S')
        logging.info(f"Iniciando o robo no papel {role if role else 'QUEUE e RANKING'}")
        
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        
        bot = InhouseBot()
        bot.run()


    

