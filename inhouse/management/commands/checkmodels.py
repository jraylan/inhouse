# -*- coding: utf-8 -*-
from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.contrib.postgres.fields import ArrayField, JSONField
from django.db import connections, connection
from django.db.backends.postgresql.schema import DatabaseSchemaEditor
from django.db.models import fields
import sys, os
import re

class Command(BaseCommand):

    help = 'Check Models'

    def add_arguments(self, parser):
        parser.add_argument('-e','--error-only','--erroronly',
                dest='erroronly',
                default=False,
                action='store_true',
                help='Exibir somente erros')

        parser.add_argument('--fix',
                dest='fix',
                action='store_true',
                default=False,
                help='Tentar Reparar erros')

        parser.add_argument('--drop',
                dest='drop',
                action='store_true',
                default=False,
                help='Se --fix foi definido, exclui colunas que não estão mais nos models.')

    def field_from_type(self, tipo):
        type_map = {
            'int4': fields.IntegerField,
            'serial': fields.AutoField,
            'bigserial': fields.BigAutoField,
            'int8': fields.BigIntegerField,
            'timestamptz': fields.DateTimeField,
            'varchar': fields.CharField,
            '_varchar': ArrayField,
            'text': fields.TextField,
            'bool': fields.BooleanField,
            'jsonb': JSONField,
            'date': fields.DateField,
            'numeric': fields.DecimalField,
            'double precision': fields.DecimalField,
            'float8': fields.DecimalField,
            'int2': fields.PositiveSmallIntegerField,
        }

        if tipo in type_map:
            return type_map[tipo]()

        return fields.CharField()

    def drop_columns(self, model, editor, cursor):
        table_name = model._meta.db_table
        schema = self.get_schema(table_name, cursor)
        connection = editor.connection

        if not schema:
            return
        
        models_fields_columns = [f.column for f in model._meta.concrete_fields if f.model == model]

        for col in schema:
            if col not in models_fields_columns:
                f = self.field_from_type(schema[col]['type'])
                f.model = model
                f.column = col
                editor.remove_field(model, f)
                print("Coluna %s removida da tabela %s" %(
                        f.column,
                        table_name
                    )
                )

    def fix_model(self,model, editor, cursor):
        table_name = model._meta.db_table
        schema = self.get_schema(table_name, cursor)
        indexs = self.get_index(table_name, cursor)
        connection = editor.connection

        if not schema:
            editor.create_model(model)
            print('Tabela %s criada' % table_name
            )
            return
        for f in self.get_many_to_many(model,cursor):
            m2m_model = f.remote_field.through
            m2m_tablename = m2m_model._meta.db_table
            print('Tabela %s criada' % m2m_tablename
            )
            editor.create_model(m2m_model)

        for f in model._meta.concrete_fields:
            if f.model != model:
                continue
            db_type = f.db_type(connection)
            col = schema.get(f.column)
            if not col:
                editor.add_field(model, f)
                print("Coluna %s adicionada na tabela %s" %(
                        f.column,
                        table_name
                    )
                )
            else:
                old_f = f.clone()
                old_f.column = f.column
                old_f.remote_field = f.remote_field
                old_f.blank = f.blank
                old_f.null = f.null
                old_f.model = model
                type_err = not self.check_type(db_type, col['type'])
                null_error = f.null != col['null']
                if null_error or type_err or (col['max_length'] and f.max_length and f.max_length != col['max_length']):
                    old_f.max_length = col['max_length']
                    if type_err:
                        old_db_params = old_f.db_parameters(connection=connection)
                        new_db_params = f.db_parameters(connection=connection)
                        editor._alter_field(model, old_f, f, col['type'], db_type,
                                            old_db_params, new_db_params, strict=False)
                        print('Tipo da coluna %s da tabela %s alterado de %s para %s' % (
                            f.column,
                            table_name,
                            col['type'],
                            db_type
                            )
                        )
                    elif null_error:
                        sql = "ALTER TABLE %s ALTER COLUMN %s %s NOT NULL"
                        sql = sql % (
                            table_name,
                            f.column,
                            "DROP" if f.null else "SET"
                            )
                        print(sql)
                        cursor.execute(sql)
                        print('Opção NOT NULL da coluna %s da tabela %s alterado de %s para %s' % (
                            f.column,
                            table_name,
                            old_f.null,
                            col['null']
                            )
                        )                        
                    else:
                        editor.alter_field(model, old_f, f)
                        print('Tamanho da coluna %s da tabela %s alterado de %s para %s' % (
                            f.column,
                            table_name,
                            old_f.max_length,
                            f.max_length
                            )
                        )
                elif not self.check_type(db_type, col['type']):
                    pass
                elif f.db_index and f.column not in indexs:
                    for sql in editor._field_indexes_sql(model, f):
                        cursor.execute(str(sql))
                        print('Index da coluna %s da tabela %s criado' % (
                            f.column,
                            table_name
                            )
                        )


    def index_to_list(self, query_result):
        index_list = []
        for col in query_result:
            index_list.append(col[1].strip().split('(')[-1][:-1])
        return index_list

    def schema_todict(self, schema):
        schema_dict = {}
        for col in schema:
            schema_dict[col[0]] = {}
            schema_dict[col[0]]['type'] = col[1]
            schema_dict[col[0]]['max_length'] = col[2]
            schema_dict[col[0]]['null'] = bool(col[3].strip() == 'YES')
        return schema_dict

    def get_many_to_many(self, model, cursor):
        fields = []
        for field in model._meta.local_many_to_many:
            if field.remote_field.through._meta.auto_created:
                table_name = field.remote_field.through._meta.db_table
                schema = self.get_schema(table_name, cursor)
                if not schema:
                    fields.append(field)
        return fields

    def get_schema(self, table_name, cursor):
        query = """
            SELECT 
               column_name, 
               udt_name,
               character_maximum_length,
               is_nullable
            FROM 
               information_schema.columns
            WHERE 
               table_name = '%s';
        """ % table_name

        cursor.execute(query)

        return self.schema_todict(cursor.cursor.fetchall())

    def get_index(self, table_name, cursor):
        query = """
            SELECT
               tablename, indexdef
            FROM
               pg_indexes
            WHERE
               tablename = '%s';
        """ % table_name

        cursor.execute(query)

        return self.index_to_list(cursor.cursor.fetchall())

    def check_type(self, model_type, db_type):
        type_map = {
            'serial': ['int4', 'serial'],
            'bigserial': ['int8', 'bigserial'],
            'integer':['int4', 'serial'],
            'bigint': ['int8'],
            'timestamp': 'timestamptz',
            'varchar': 'varchar',
            'varchar[]': '_varchar',
            'text': ['text', '_varchar'],
            'boolean': 'bool',
            'jsonb': 'jsonb',
            'date': 'date',
            'numeric': 'numeric',
            'double': ['double precision', 'float8'],
            'smallint': 'int2'

        }
        model_type = model_type.split()[0]
        model_type = re.sub(r'([0-9\(\),])', '', model_type)
        if model_type != db_type:
            if db_type not in type_map[model_type]:
                return False
        return True

    def check_fields(self, model, cursor):
        err_fields = []
        table_name = model._meta.db_table

        schema = self.get_schema(table_name, cursor)
        connection = cursor.db.client.connection
        models_fields = [f for f in model._meta.concrete_fields if f.model == model]
        indexs = self.get_index(table_name, cursor)


        #print(table_name)
        for f in models_fields:
            if f.model != model:
                continue
            db_type = f.db_type(connection)
            col = schema.get(f.column)
            if not col:
                err_fields.append({'table': table_name, 'column': f.column, 'error': 'Coluna nao declarada no banco'})
            elif col['max_length'] and f.max_length and f.max_length != col['max_length']:
                err_fields.append({'table': table_name, 'column': f.column, 'error': 'Tamanho maximo diferente do declarado (%s, %s)' % (f.max_length, col['max_length'])})
            elif not self.check_type(db_type, col['type']):
                err_fields.append({'table': table_name, 'column': f.column, 'error': 'Tipo de dado diferente do declarado (%s, %s)' % (db_type,col['type'])})
            elif f.null != col['null']:
                err_fields.append({'table': table_name, 'column': f.column, 'error': 'Opção not null no banco divergente do módel (%s, %s)' % (f.null,col['null'])})
                schema[f.column]['check'] = True
            elif f.db_index and f.column not in indexs:
                err_fields.append({'table': table_name, 'column': f.column, 'error': 'Index não declarado'})
                schema[f.column]['check'] = True
            else:
                schema[f.column]['check'] = True

        for k in schema:
            if not schema[k].get('check', False):
                err_fields.append({'table': table_name, 'column': k, 'error': 'A coluna não está declarada no model'})


        fields = self.get_many_to_many(model, cursor)
        for f in fields:
            err_fields.append({'table': table_name, 'column': f.column, 'error': 'Tablela do M2M nao declarada'})

        return err_fields

    def handle(self, *args, **options):
        if sys.version_info < (3,0):
            reload(sys)
            sys.setdefaultencoding('utf-8')

        fix = options.get('fix')
        drop = options.get('drop')
        erroronly = options.get('erroronly') or fix

        errados = []
        checados = []
        pulados = []

        with connection.cursor() as cursor:
            models = {
                "%s.%s" % (model.__module__, model.__name__): model for model in apps.get_models()
            }
            for name, model in models.items():
                out = name
                if model._meta.proxy or (hasattr(model._meta, 'managed') and not model._meta.managed):
                    os.system('tput setaf 3')
                    pulados.append(out)
                    out = "[SKIP]\t%s" % out
                else:
                    checados.append(out)
                    os.system('tput setaf 1')
                    errs = self.check_fields(model, cursor)
                    if errs:
                        errados.append(model)
                        out = "[ERROR]\t%s" % out
                        for err in errs:
                            out +="\n\t- Tabela: %s, Coluna: %s. %s." % (err['table'], err['column'], err['error'])
                    else:
                        os.system('tput setaf 2')
                        out = "[OK]\t%s" % out
                if erroronly:
                    if '[ERROR]' in out:
                        print(out)
                else:
                    print(out)
                os.system('tput sgr0')
            print('')
            print('Checados: %s, Pulados: %s, Erros: %s' % (len(checados), len(pulados), len(errados)))

            if fix:
                with DatabaseSchemaEditor(cursor.db.client.connection) as editor:
                    for model in errados:
                        self.fix_model(model, editor, cursor)
                        if drop:
                            self.drop_columns(model, editor, cursor)
