set -e

LOCAL_PROXY=http://10.126.6.88:3128

IMAGE_NAME=gitlab.dellin.ru:5005/alozhkin/gpn_logistic_2.0/parallela/cplex_version
IMAGE_VERSION=$(date +"%Y-%m-%d_%H-%m")

docker build -f Dockerfile_parallela --build-arg http_proxy=${LOCAL_PROXY} --build-arg https_proxy=${LOCAL_PROXY} -t ${IMAGE_NAME}:${IMAGE_VERSION} .
docker tag ${IMAGE_NAME}:${IMAGE_VERSION} ${IMAGE_NAME}:latest

docker push ${IMAGE_NAME}:${IMAGE_VERSION}
docker push ${IMAGE_NAME}:latest
