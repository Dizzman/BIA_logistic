ARG DOCKER_IMAGE=gitlab.dellin.ru:5005/alozhkin/gpn_logistic_2.0/pythoncplex-centos:latest

FROM $DOCKER_IMAGE

WORKDIR /tmp/gpn_logistic_2.0

COPY . .

RUN pip install flask matplotlib

RUN chmod -R 777 /tmp/gpn_logistic_2.0 && \
    localedef -i ru_RU -f UTF-8 ru_RU.UTF-8

ENV LC_ALL ru_RU.UTF-8

CMD ["python3.6", "/tmp/gpn_logistic_2.0/rest/wsgi.py"]
