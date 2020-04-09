docker login gitlab.dellin.ru:5005
docker build --build-arg http_proxy=http://10.126.6.57:3128 --build-arg https_proxy=http://10.126.6.57:3128 -f Dockerfile_centos -t gitlab.dellin.ru:5005/alozhkin/gpn_logistic_2.0/gpntest .
docker push gitlab.dellin.ru:5005/alozhkin/gpn_logistic_2.0/gpntest
