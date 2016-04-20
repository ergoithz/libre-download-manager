# distutils setup file

from distutils.core import setup, Command
from distutils.command.install import install as _install

from glob import glob
import sys
import os


# Constants
import constants.constants as c

author, author_email = c.APP_AUTHOR.rsplit(' ', 1)

appname = c.APP_NAME.lower().replace(' ', '-')


class install(_install):
    def run(self):
        _install.run(self)

        # Put now the .desktop file!
        os.system('update-desktop-database data')

        # TODO: put the right directory for the icon and executable,
        # maybe using something like this:
        # from xdg.BaseDirectory
        # import xdg_config_home


class build_trans(Command):
    description = 'Compile .po files into .mo files'
    user_options = [('build-lib', None, "lib build folder")]

    def initialize_options(self):
        self.build_lib = None

    def finalize_options(self):
        self.set_undefined_options('build', ('build_lib', 'build_lib'))

    def run(self):
        # The way I update the po files:
        #   xgettext -L Python --from-code "utf-8" server/templates/*.html  `find -name '*.py'`
        #   poedit locale/es/LC_MESSAGES/downloader.po
        # and select the "catalog -> update from pot file -> footorrent/message.po"
        print "Generating binary translation files (.mo) from originals (.po)"

        for lang in ["en", "es", "fr"]:
            print "  Lang: %s" % lang
            os.system("msgfmt locale/%s/LC_MESSAGES/downloader.po "
                      "-o locale/%s/LC_MESSAGES/downloader.mo" % (lang, lang))

        print 'Compiling po files from %s...' % po_dir,
        for path,names,filenames in os.walk(po_dir):
            for f in filenames:
                if not f.endswith('.po'):
                    continue
                uptoDate = False
                lang = f[:-3]
                src = os.path.join(path, f)
                dest_path = os.path.join(self.build_lib, appname, 'locale',
                                         lang, 'LC_MESSAGES')
                dest = os.path.join(dest_path, 'downloader.mo')
                if not os.path.exists(dest_path):
                    os.makedirs(dest_path)
                if not os.path.exists(dest):
                    sys.stdout.write('%s, ' % lang)
                    sys.stdout.flush()
                    msgfmt.make(src, dest)
                else:
                    src_mtime = os.stat(src)[8]
                    dest_mtime = os.stat(dest)[8]
                    if src_mtime > dest_mtime:
                        sys.stdout.write('%s, ' % lang)
                        sys.stdout.flush()
                        msgfmt.make(src, dest)
                    else:
                        uptoDate = True

        if uptoDate:
            sys.stdout.write(' po files already upto date.  ')
        sys.stdout.write('\b\b \nFinished compiling translation files. \n')




class build_plugins(Command):
    description = "Build plugins into .eggs"
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        # Build the plugin eggs
        for path in glob('plugins/*'):
            if os.path.exists(os.path.join(path, "setup.py")):
                os.system('cd %s && %s setup.py bdist_egg -d ..' %
                          (path, sys.executable))



setup(name=appname,
      version=c.APP_VERSION,
      description="%s is a fast and easy to use P2P client." % c.APP_NAME,
      author=author,
      author_email=author_email.strip('<>'),
      keywords = "torrent bittorrent p2p fileshare filesharing",
      license='GNU Affero GPL',
      url=c.APP_URL,
      cmdclass={'install': install,
                'build_trans': build_trans,
                'build_plugins': build_plugins},
      packages=['config', 'constants', 'my_env', 'backends', 'backends/ec',
                'server', 'wxproxy', 'extras', 'zipsign'],
      data_files=[('svg', glob('svg/*')),
                  ('locale/en/LC_MESSAGES', glob('locale/en/LC_MESSAGES/*')),
                  ('locale/es/LC_MESSAGES', glob('locale/es/LC_MESSAGES/*')),
                  ('locale/fr/LC_MESSAGES', glob('locale/fr/LC_MESSAGES/*')),
                  ('data', glob('data/*')),
                  ('gui', glob('gui/*')),
                  ('icons', glob('icons/*')),
                  ('server/templates', glob('server/templates/*')),
                  ('server/static/css', glob('server/static/css/*')),
                  ('server/static/imgs', glob('server/static/imgs/*')),
                  ('server/static/js', glob('server/static/js/*'))],
      py_modules=['front', 'utils', 'gui'],
      scripts=[appname])
