import restu

restu.init()
sidecar = restu.start_sidecar()

application = restu.app

if __name__ == '__main__':
    restu.app.run(host='0.0.0.0')
