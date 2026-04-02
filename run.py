from app import create_app

app = create_app()

if __name__ == "__main__":
    print("Lancement du serveur...")
    app.run(debug=False)  # Désactiver le debug mode