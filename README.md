# Reportix
An easier way to grab your computer specs in a PDF report.

> The app is only tested on Linux and Windows

**Prerequisites**
Python 3.8 or higher installed on your system.

**Installation**
Open a terminal in the project directory and run the following commands to create a virtual environment and install the required dependencies.

```bash
python -m venv venv
venv\Scripts\activate     # Linux: source venv/bin/activate 
pip install -r requirements.txt
```

**Usage**
Start the application by running the main script.

```bash
python app.py
```

**Building the Application**
To package the project into a standalone executable file, you can use PyInstaller.

Install PyInstaller in your active virtual environment:

```bash
pip install pyinstaller
```

Run the build command from the project root directory:

```bash
pyinstaller --onefile --noconsole --name "Reportix-v1.0.0-portable" app.py
```

The compiled standalone executable will be created inside the `dist` folder.