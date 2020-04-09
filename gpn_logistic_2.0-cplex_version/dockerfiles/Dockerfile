ARG DOCKER_IMAGE=gitlab.dellin.ru:5005/alozhkin/gpn_logistic_2.0/python-cplex:latest
FROM $DOCKER_IMAGE

WORKDIR /tmp/gpn_logistic_2.0

RUN pip install flask

COPY . .

RUN chmod -R 777 /tmp/gpn_logistic_2.0

CMD ["python3.6", "/tmp/gpn_logistic_2.0/rest/rest.py"]
