const { app, BrowserWindow, ipcMain, globalShortcut, Tray, Menu, nativeImage, session } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn, exec } = require('child_process');
const http = require('http');

let mainWindow;
let pyProcess = null;
let tray = null;
let isQuitting = false;

// Set VANI_DESKTOP env
process.env.VANI_DESKTOP = '1';

function startPythonBackend() {
  const rootDir = path.join(__dirname, '..');
  let pythonPath = 'python';

  // Search for Python virtual env
  const venvPaths = [
    path.join(rootDir, '.venv', 'Scripts', 'python.exe'),
    path.join(rootDir, 'venv311', 'Scripts', 'python.exe'),
    path.join(rootDir, 'venv311_new', 'Scripts', 'python.exe'),
    path.join(rootDir, '.venv', 'bin', 'python'),
    path.join(rootDir, 'venv311', 'bin', 'python'),
    path.join(rootDir, 'venv311_new', 'bin', 'python'),
  ];

  for (const vp of venvPaths) {
    if (fs.existsSync(vp)) {
      pythonPath = vp;
      break;
    }
  }

  console.log(`[Electron Main] Spawning Python backend using: ${pythonPath}`);
  
  const env = Object.assign({}, process.env, {
    PYTHONPATH: path.join(rootDir, 'src'),
    PYTHONUNBUFFERED: '1',
    VANI_DESKTOP: '1'
  });

  pyProcess = spawn(pythonPath, ['-m', 'vani.launcher'], {
    cwd: rootDir,
    env: env,
    shell: true
  });

  pyProcess.stdout.on('data', (data) => {
    console.log(`[Python] ${data.toString().trim()}`);
  });

  pyProcess.stderr.on('data', (data) => {
    console.error(`[Python Err] ${data.toString().trim()}`);
  });

  pyProcess.on('close', (code) => {
    console.log(`[Electron Main] Python process exited with code ${code}`);
    pyProcess = null;
  });
}

function stopPythonBackend() {
  return new Promise((resolve) => {
    if (!pyProcess) {
      resolve();
      return;
    }
    console.log('[Electron Main] Stopping Python backend process tree...');
    if (process.platform === 'win32') {
      exec(`taskkill /pid ${pyProcess.pid} /f /t`, (err) => {
        if (err) {
          console.error('[Electron Main] Failed to kill python process tree:', err);
        }
        pyProcess = null;
        resolve();
      });
    } else {
      pyProcess.kill('SIGINT');
      pyProcess = null;
      resolve();
    }
  });
}

function waitForServer(url, callback) {
  let attempts = 0;
  const check = () => {
    http.get(url, (res) => {
      if (res.statusCode === 200) {
        console.log(`[Electron Main] Server is active at ${url}`);
        callback();
      } else {
        attempts++;
        if (attempts % 10 === 0) console.log(`[Electron Main] Waiting for server on port 5500...`);
        setTimeout(check, 500);
      }
    }).on('error', () => {
      attempts++;
      if (attempts % 10 === 0) console.log(`[Electron Main] Waiting for server connection...`);
      setTimeout(check, 500);
    });
  };
  check();
}

function createWindow() {
  const iconPath = path.join(__dirname, 'icon.png');
  const windowIcon = fs.existsSync(iconPath) ? nativeImage.createFromPath(iconPath) : null;

  mainWindow = new BrowserWindow({
    width: 480,
    height: 720,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: true,
    icon: windowIcon,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      autoplayPolicy: 'no-user-gesture-required'
    }
  });

  mainWindow.loadURL('http://127.0.0.1:5500/');

  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function createTray() {
  const iconPath = path.join(__dirname, 'icon.png');
  let trayImage;
  
  if (fs.existsSync(iconPath)) {
    trayImage = nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 });
  } else {
    trayImage = nativeImage.createEmpty();
  }

  tray = new Tray(trayImage);
  const contextMenu = Menu.buildFromTemplate([
    { 
      label: 'Show Siya', 
      click: () => { 
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      } 
    },
    { 
      label: 'Hide Siya', 
      click: () => { 
        if (mainWindow) mainWindow.hide(); 
      } 
    },
    { type: 'separator' },
    { 
      label: 'Restart Backend', 
      click: async () => {
        console.log('[Electron Main] Restarting backend via tray menu...');
        if (mainWindow) mainWindow.hide();
        await stopPythonBackend();
        startPythonBackend();
        waitForServer('http://127.0.0.1:5500/', () => {
          if (mainWindow) {
            mainWindow.loadURL('http://127.0.0.1:5500/');
            mainWindow.show();
          }
        });
      } 
    },
    { type: 'separator' },
    { 
      label: 'Quit', 
      click: () => { 
        isQuitting = true;
        app.quit(); 
      } 
    }
  ]);

  tray.setToolTip('Siya AI Assistant');
  tray.setContextMenu(contextMenu);

  tray.on('click', () => {
    if (mainWindow) {
      if (mainWindow.isVisible()) {
        mainWindow.hide();
      } else {
        mainWindow.show();
        mainWindow.focus();
      }
    }
  });
}

function registerGlobalHotkey() {
  const shortcut = 'CommandOrControl+Shift+V';
  const registered = globalShortcut.register(shortcut, () => {
    console.log(`[Electron Main] Global Shortcut (${shortcut}) triggered`);
    if (mainWindow) {
      if (mainWindow.isVisible()) {
        mainWindow.hide();
      } else {
        mainWindow.show();
        mainWindow.focus();
      }
    }
  });

  if (registered) {
    console.log(`[Electron Main] Registered global shortcut: ${shortcut}`);
  } else {
    console.warn(`[Electron Main] Failed to register global shortcut: ${shortcut}`);
  }
}

ipcMain.on('app-quit', () => {
  isQuitting = true;
  app.quit();
});

ipcMain.on('app-minimize', () => {
  if (mainWindow) mainWindow.minimize();
});

app.whenReady().then(() => {
  // Auto-approve microphone/speaker requests
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    if (permission === 'media') {
      return callback(true);
    }
    callback(false);
  });

  session.defaultSession.setPermissionCheckHandler((webContents, permission, origin) => {
    if (permission === 'media') {
      return true;
    }
    return false;
  });

  startPythonBackend();
  createTray();
  registerGlobalHotkey();
  waitForServer('http://127.0.0.1:5500/', () => {
    createWindow();
  });
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

app.on('will-quit', async (event) => {
  globalShortcut.unregisterAll();
  event.preventDefault();
  await stopPythonBackend();
  process.exit(0);
});
