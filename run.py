from app import create_app

app = create_app()

if __name__ == "__main__":
    print("Lancement du serveur...")
    app.run(debug=True)  # debug=True enables auto-reload on code changes
