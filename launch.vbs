Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
strPath = fso.GetParentFolderName(WScript.ScriptFullName)

' Build the full path to the venv Python
strPython = fso.BuildPath(strPath, "venv\Scripts\python.exe")
strApp = fso.BuildPath(strPath, "app.py")

' Start the Flask server hidden (no black window)
WshShell.Run """" & strPython & """ """ & strApp & """", 0, False

' Wait for the server to start
WScript.Sleep 3000

' Open the browser
WshShell.Run "http://localhost:5000", 1, False
