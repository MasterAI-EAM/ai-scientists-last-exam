"""Install genuine desktop dependencies in the disposable Computer1 live task."""
from pathlib import Path

PACKAGES=('xvfb','xauth','xfce4-session','xfwm4','xfce4-settings','dbus-x11',
          'chromium','xdotool','wmctrl','imagemagick','webp','scrot','fonts-dejavu-core','x11-utils')

def configure(task:Path):
    dockerfile=task/'environment'/'Dockerfile'
    block='\nRUN apt-get -o Acquire::Retries=8 update && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=8 install -y --no-install-recommends '+' '.join(PACKAGES)+' && rm -rf /var/lib/apt/lists/*\n'
    dockerfile.write_text(dockerfile.read_text()+block)
