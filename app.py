from eco_basket.application import app, env_bool


if __name__ == '__main__':
    app.run(debug=env_bool('FLASK_DEBUG', False))

