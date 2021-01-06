### Installation

```
git clone git@github.com/jraylan/inhouse2.git inhouse
```

```
cd inhouse
```

```
pip3 install -r requirements.txt
```

As variáveis de ambiente estão no arquivo inhouse-rc

```
source rc-inhouse
```

Cria as migrações do banco

```
python3 manage.py makemigrations inhouse
```

Aplica as migrações

```
python3 manage.py migrate
```

Inicia o robô. É possível definir o papel desse robo, caso queira limitar-lo a essa função.

```
python3 manage.py run_bot [--role=(QUEUE|RANKING)] [--log-level=(CRITICAL|ERROR|WARNING|INFO|DEBUG)]
```

#### Todo
 - Tornar um Service
 - Dockerizar
