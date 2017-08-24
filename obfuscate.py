#!/usr/bin/python

import re
import os
import sys
import string
import random
import argparse

# TODO: Switch this
DEBUG = False 

config = {
	'verbose' : False,
	'quiet' : False,
	'file' : '',
	'output' : '',
	'garbage_perc' : 12.0,
	'min_var_length' : 5,
	'custom_reserved_words': [],
	'normalize_only': False
}

def out(x):
	if not config['quiet']:
		sys.stderr.write(x + '\n')

def log(x):
	if config['verbose']:
		out(x)

def err(x):
	out('[!] ' + x)

def info(x):
	log('[?] ' + x)

def ok(x):
	log('[+] ' + x)

class ScriptObfuscator():

	RESERVED_NAMES = (
		"AutoExec",
		"AutoOpen",
		"DocumentOpen",
		"AutoExit",
		"AutoClose",
		"Document_Close",
		"DocumentBeforeClose",
		"Document_Open",
		"Document_BeforeClose",
		"Auto_Open",
		"Workbook_Open",
		"Workbook_Activate",
		"Auto_Close",
		"Workbook_Close"
	)

	STRINGS_REGEX = r"(\"(?:[^\"\n]|\"\")+\")"

	FUNCTION_REGEX = r"(?:Public|Private|Protected|Friend)?\s*(?:Sub|Function)\s+(\w+)\s*\(.*\)"

	# var = "value" _\n& "value"
	LONG_LINES_REGEX = r"(?:(?:(\w+)\s*=\s*)|(?:\s*&\s+))\"([^\"]+)\"(?:\s+_)?"

	# Dim var ; Dim Var As Type ; Set Var = [...] ; Const Var = [...]
	VARIABLES_REGEX = r"(?:(?:Dim|Set|Const)\s+(\w+)\s*(?:As|=)?)|(?:^(\w+)\s+As\s+)"

	# Dim Var1, var2, va3 As Type
	VARIABLE_DECLARATIONS_REGEX = r"Dim\s+(?:(?:\s*,\s*)?(\w+)(?:\s*,\s*)?)+"

	FUNCTION_PARAMETERS_REGEX = r"(?:(?:Optional\s*)?(?:ByRef|ByVal\s*)?(\w+)\s+As\s+\w+\s*,?\s*)"

	# Public Dim Var As Type ; Public Declare PtrSafe [...]
	GLOBALS_REGEX = r"\s*(?:(?:Public|Private|Protected)\s*(?:Dim|Set|Const)?\s+(\w+)\s*As)|(?:(?:Private|Protected|Public)\s+Declare\s+PtrSafe?\s*Function\s+(\w+)\s+)"


	def __init__(self, normalize_only, reserved_words, garbage_perc, min_var_length):
		self.input = ''
		self.output = ''
		self.function_boundaries = []
		self.normalize_only = normalize_only
		self.garbage_perc = garbage_perc
		self.min_var_length = min_var_length
		self.reserved_words = reserved_words

	def obfuscate(self, inp):
		self.input = inp
		self.output = inp

		# Normalization processes, not obfuscating at the moment.
		# 	Step 0a: Merge long string lines and split them to concatenate.
		self.mergeAndConcatLongLines()

		if self.normalize_only:
			return self.output

		# Step 1: Remove comments
		self.output = re.sub(r"(?<!\"[^\"])'(.*)", "", self.output, flags=re.I)

		# Step 2: Rename used variables
		self.randomizeVariablesAndFunctions()

		# Step 3: Explode string constants
		self.obfuscateStrings()

		# Step 4: Obfuscate arrays
		self.obfuscateArrays()

		# Step 5: Insert garbage
		self.insertGarbage()

		# Step 6: Remove empty lines
		self.output = '\n'.join(filter(lambda x: not re.match(r'^\s*$', x), self.output.split('\n')))
		
		# Step 7: Remove indents and multi-spaces.
		if not DEBUG:
			self.output = re.sub(r"\t| {2,}", "", self.output, flags=re.I)

		return self.output

	def detectFunctionBoundaries(self):
		pos = 0
		del self.function_boundaries[:]
		funcStart = 0
		funcStop = 0
		counter = 0

		for m in re.finditer(ScriptObfuscator.FUNCTION_REGEX, self.output, flags=re.I|re.M):
			if pos >= len(self.output): break

			funcName = m.group(1)
			funcStart = m.span()[0] + (len(m.group(0)) - len(m.group(0).lstrip()))
			
			if counter > 0: 
				rev = self.output[pos:funcStart].rfind('End Sub')
				if rev == -1:
					rev = self.output[pos:funcStart].rfind('End Function')

				prev_end = pos + rev
				pos = prev_end
				self.function_boundaries[counter - 1]['funcStop'] = prev_end
				prev = self.function_boundaries[counter - 1]
				info("Function boundaries: (%s, from: %d, to: %d)" % (prev['funcName'], prev['funcStart'], prev['funcStop']))
			
			elem = {
				'funcName' : funcName,
				'funcStart' : funcStart,
				'funcStop' : -1
			}
			self.function_boundaries.append(elem)
			counter += 1

	def isInsideFunc(self, pos, offset = 0):
		for func in self.function_boundaries:
			if pos > (offset + func['funcStart']) and pos < (offset + func['funcStop']):
				return True
		return False

	def getFuncBoundaries(self, name):
		for func in self.function_boundaries:
			if name == func['funcName']:
				return func
		return None

	def mergeAndConcatLongLines(self):
		SPLIT = 80
		rex = ScriptObfuscator.LONG_LINES_REGEX
		pos = 0
		replaces = []

		for m in re.finditer(rex, self.output[pos:], flags=re.I|re.M):
			varName = m.group(1)
			longLine = m.group(2)
			if len(longLine) < SPLIT: continue
			
			pos = m.span()[1]
			endOfLine = pos + self.output[pos:].find('\n')
			suffix = self.output[pos:endOfLine + 1]
			
			lineStart = m.span()[0]
			pos += len(suffix)		
			lineStop = pos

			while True:
				if pos >= len(self.output): break
				endOfLine = pos + self.output[pos:].find('\n')
				n = re.match(rex, self.output[pos:endOfLine], flags=re.I|re.M)
				pos += endOfLine - pos + 1
				if not n: 
					break

				longLine += n.group(2)
				
			lineStop = pos
			origLine = self.output[lineStart:lineStop]
			info("Merging long string line (var: %s, len: %d): '%s...%s'" % (varName, len(longLine), longLine[:40], longLine[-40:]))
			newLine = ''
			for s in range(len(longLine) / SPLIT + 1):
				fr = s * SPLIT
				to = fr + SPLIT
				if newLine == '':
					newLine += '%s = "%s"\n' % (varName, longLine[fr:to])
				else:
					newLine += '%s = %s + "%s"\n' % (varName, varName, longLine[fr:to])

			replaces.append((origLine, newLine))
			if pos >= len(self.output): break

		for (orig, new) in replaces:
			self.output = self.output.replace(orig, new)


	def randomizeVariablesAndFunctions(self):
		def replaceVar(name, m):
			varName = randomString(random.randint(4,12))
			varToReplace = filter(lambda x: x and len(x)>0, m.groups())[0]

			if len(varToReplace) < self.min_var_length: return
			if varToReplace in self.reserved_words: return
			info(name + " name obfuscated (context: \"%s\"): '%s' => '%s'" % (m.group(0).strip(), varToReplace, varName))
			self.output = re.sub(r"(?:\b" + varToReplace + r"\b)|(?:" + varToReplace + r"\s*=\s*)", varName, self.output, flags=re.I | re.M)

		# Variables
		for m in re.finditer(ScriptObfuscator.VARIABLES_REGEX, self.output, flags = re.I|re.M):
			replaceVar('Variable', m)

		for m in re.finditer(ScriptObfuscator.VARIABLE_DECLARATIONS_REGEX, self.output, flags = re.I|re.M):
			replaceVar('Variable', m)

		# Globals
		for m in re.finditer(ScriptObfuscator.GLOBALS_REGEX, self.output, flags = re.I|re.M):
			replaceVar('Global', m)

		# Function parameters
		self.detectFunctionBoundaries()

		for m in re.finditer(ScriptObfuscator.FUNCTION_REGEX, self.output, flags = re.I|re.M):
			pos = m.span()[0]
			funcName = m.group(1)
			replaces = []

			for n in re.finditer(ScriptObfuscator.FUNCTION_PARAMETERS_REGEX, m.group(0), flags=re.I|re.M):
				pos2 = n.span()[0]
				varName = randomString(random.randint(4,12))
				varToReplace = n.group(1)
				replaces.append((varToReplace, varName))

			func = self.getFuncBoundaries(funcName)
			start = max(func['funcStart'] - len(m.group(0)), 0)
			funcCode = self.output[start:func['funcStop']]
			pre_func = self.output[:start]
			post_func = self.output[func['funcStop']:]

			for repl in replaces:
				info("Function argument obfuscated (%s): (%s) => (%s)" % (funcName, repl[0], repl[1]))
				out = re.sub(r"\b" + repl[0] + r"\b", repl[1], funcCode, flags=re.I|re.M)
				self.output = pre_func + out + post_func

		# Functions
		for m in re.finditer(ScriptObfuscator.FUNCTION_REGEX, self.output, flags = re.I|re.M):
			varName = randomString(random.randint(4,12))
			varToReplace = m.group(1)
			if len(varToReplace) < self.min_var_length: continue
			if varToReplace in self.reserved_words: continue
			if varToReplace in ScriptObfuscator.RESERVED_NAMES: continue
			info("Function name obfuscated (context: \"%s\"): '%s' => '%s'" % (m.group(0).strip(), varToReplace, varName))
			self.output = re.sub(r"\b" + varToReplace + r"\b", varName, self.output, flags=re.I | re.M)


	def obfuscateNumber(self, num):
		rnd1 = random.randint(0, 3333)
		num_coders = (
			lambda rnd1, num: '%d' % num,
			lambda rnd1, num: '%d-%d' % (rnd1+num, rnd1),
			lambda rnd1, num: '%d-%d' % (2*rnd1+num, 2*rnd1),
			lambda rnd1, num: '%d-%d' % (3*rnd1+num, 3*rnd1),
			lambda rnd1, num: '%d+%d' % (-rnd1, rnd1+num),
			lambda rnd1, num: '%d/%d' % (rnd1*num, rnd1),
		)

		return random.choice(num_coders)(rnd1, num)

	def obfuscateChar(self, char):
		char_coders = (
			lambda x: 'Chr(&H%x)' % ord(x),
			lambda x: 'Chr(%d)' % ord(x),
			lambda x: '"{}"'.format(x),
			lambda x: 'Chr(%s)' % self.obfuscateNumber(ord(x)),
			lambda x: 'Chr(Int("&H%x"))' % ord(x),
			lambda x: 'Chr(Int("%d"))' % ord(x),
		)
		out = random.choice(char_coders)(char)
		return out

	def obfuscateString(self, string):
		if len(string) == 0: return ""
		new_string = ''
		delim = '&'
		if DEBUG: delim = ' & '

		i = 0
		while i < len(string):
			char = string[i]
			if i + 1 < len(string):
				if char == '"' and string[i+1] == '"':
					i += 2
					new_string += '""""' + delim
					continue
			if char == '"':
				# Fix improper quote escape
				new_string += '""""' + delim
				i += 1
				continue

			new_string += self.obfuscateChar(char) + delim
			i += 1

		return new_string[:-len(delim)]

	def obfuscateStrings(self):
		replaces = set()
		for m in re.finditer(ScriptObfuscator.STRINGS_REGEX, self.output, flags=re.I|re.M):
			orig_string = m.group(1)
			string = orig_string[1:-1]

			opening = max(m.span()[0]-500, 0)
			line_start = opening + self.output[opening:m.span()[0]].rfind('\n') + 1
			line_stop = m.span()[1] + self.output[m.span()[1]:].find('\n') + 1
			line = self.output[line_start:line_stop]


			if 'declare' in line.lower() \
				and 'ptrsafe' in line.lower() \
				and 'function' in line.lower():
				# Syntax error while obfuscating pointer names and libs
				if self.garbage_perc > 0:
					varName = randomString(random.randint(8,20))
					varName2 = randomString(random.randint(8,20))
					junk = self.obfuscateString(randomString(random.randint(40,80)))
					junk2 = self.obfuscateString(randomString(random.randint(40,80)))
					garbage = '\'Dim %(varName)s\n\'Set %(varName)s = %(varContents)s\n' % \
					{'varName' : varName, 'varContents' : junk}
					garbage2 = '\'Dim %(varName)s\n\'Set %(varName)s = %(varContents)s\n' % \
					{'varName' : varName2, 'varContents' : junk2}

					replaces.add((line, garbage + line + garbage2))
				continue

			info("String to obfuscate (context: {{%s}}): {{%s}}" % (m.group(0).strip(), string))
			new_string = self.obfuscateString(string)
			info("\tObfuscated: ({{%s}}) => ({{%s}}...)" % (string, new_string))

			replaces.add((orig_string, new_string))

		for (orig, new) in replaces:
			self.output = self.output.replace(orig, new)

	def obfuscateArrays(self):
		for m in re.finditer(r"\bArray\s*\(([^\)]+?)\)", self.output, flags=re.I|re.M):
			orig_array = m.group(1)
			array = orig_array
			array = array.replace('\n', '').replace('\t', '')
			info("Array to obfuscate: Array(%s, ..., %s)" % (array[:40], array[-40:]))
			for_nums_allowed = [x for x in string.digits[:]]
			for_nums_allowed.extend(['a', 'b', 'c', 'd', 'e', 'f', ' ', '-', '_', '&', ','])
			if all(map(lambda x: x in for_nums_allowed, array)):
				# Array of numbers
				array = array.replace(' ', '').replace('_', '')
				try:
					info("\tLooks like array of numbers.")
					new_array = []
					nums = array.split(',')
					for num in nums:
						num = num.strip()
						new_array.append(self.obfuscateNumber(int(num)))

					obfuscated = 'Array(' + ','.join(new_array) + ')'
					info("\tObfuscated array: Array(%s, ..., %s)" % (','.join(new_array)[:40], ','.join(new_array)[-40:]))
					self.output = re.sub(r"Array\s*\(" + orig_array + "\)", obfuscated, self.output, flags=re.I | re.M)

				except ValueError as e:
					info("\tNOPE. This is not an array of numbers. Culprit: ('%s', context: '%s')" % (num, m.group(0)))
					continue
			else:
				info("\tThis doesn't seems to be array of numbers. Other types not supported at the moment.")


	def insertGarbage(self):
		if self.garbage_perc == 0.0:
			return

		self.detectFunctionBoundaries()

		lines = self.output.split('\n')
		inside_func = False
		garbages_num = int((self.garbage_perc / 100.0) * len(lines))
		new_lines = ['' for x in range(len(lines) + garbages_num)]
		garbage_lines = [random.randint(0, len(new_lines)-1) for x in range(garbages_num)]

		info('Appending %d garbage lines to the %d lines of input code %s' % \
			(garbages_num, len(lines), str(garbage_lines)))

		j = 0
		pos = 0
		offset = 0

		for i in range(len(new_lines)):
			if j >= len(lines): break

			inside_func = self.isInsideFunc(pos)

			if i in garbage_lines:
				comment = True
				if inside_func:
					comment = False

				varName = randomString(random.randint(4,12))
				varContents = self.obfuscateString(randomString(random.randint(10,30)))
				garbage = ''
				if comment:
					garbage = '\'Dim %(varName)s\n\'Set %(varName)s = %(varContents)s' % \
					{'varName' : varName, 'varContents' : varContents}
				else:
					garbage = 'Dim %(varName)s\nSet %(varName)s = %(varContents)s' % \
					{'varName' : varName, 'varContents' : varContents}

				# TODO:
				new_lines[i] = garbage
				offset += 2
			else:
				new_lines[i] = lines[j]
				pos += len(lines[j]) + 1
				j += 1

		self.output = '\n'.join(new_lines)


def randomString(len):

	rnd = ''.join(random.choice(
		string.letters + string.digits
	) for _ in range(len))

	if rnd[0] in string.digits:
		rnd = random.choice(string.letters) + rnd

	return rnd

def parse_options(argv):
	global config
	args = None

	parser = argparse.ArgumentParser(
		prog = 'obfuscate.py',
		description = '''
	Attempts to obfuscate an input visual basic script in order to prevent
	curious eyes from reading over it.
''')

	group = parser.add_mutually_exclusive_group()
	group2 = parser.add_mutually_exclusive_group()
	parser.add_argument("input_file", help="Visual Basic script to be obfuscated.")
	parser.add_argument("-o", "--output", help="Output file. Default: stdout", default='')
	group2.add_argument("-N", "--normalize", dest="normalize_only", help="Don't perform obfuscation, do only code normalization (like long strings transformation).", action='store_true')
	group2.add_argument("-g", "--garbage", help="Percent of garbage to append to the obfuscated code. Default: 12%%.", default=config['garbage_perc'], type=float)
	group2.add_argument("-G", "--no-garbage", dest="nogarbage", help="Don't append any garbage.", action='store_true')
	parser.add_argument("-m", "--min-var-len", dest='min_var_len', help="Minimum length of variable to include in name obfuscation. Too short value may break the original script. Default: 5.", default=config['min_var_length'], type=int)
	parser.add_argument("-r", "--reserved", action='append', help='Reserved word/name that should not be obfuscated (in case some name has to be in original script cause it may break it otherwise). Repeat the option for more words.')
	group.add_argument("-v", "--verbose", help="Verbose output.", action="store_true")
	group.add_argument("-q", "--quiet", help="No unnecessary output.", action="store_true")

	args = parser.parse_args()

	if args.verbose:
		config['verbose'] = True

	if not args:
		parser.print_help()

	if not os.path.isfile(args.input_file):
		err('Input file does not exist!')
		return False
	else:
		config['file'] = args.input_file

	if args.output:
		config['output'] = args.output

	if args.normalize_only:
		config['normalize_only'] = args.normalize_only

	if args.quiet:
		config['quiet'] = True

	if args.garbage <= 0.0 or args.garbage > 100.0:
		err("Garbage parameter must be in range (0, 100)!")
		return False
	else:
		config['garbage_perc'] = args.garbage

	if args.nogarbage:
		config['garbage_perc'] = 0.0

	if args.min_var_len < 0:
		err("Minimum var length must be greater than 0!")
	else:
		config['min_var_len'] = args.min_var_len

	if args.reserved:
		for r in args.reserved:
			config['custom_reserved_words'].append(r)

	return True

def main(argv):

	if not parse_options(argv):
		return False

	out('''
	Visual Basic script obfuscator for penetration testing usage.
	Mariusz B. / mgeeky, '17
''')

	ok('Input file:\t\t"%s"' % config['file'])
	if config['output']:
		ok('Output file:\t"%s"' % config['output'])
	else:
		ok('Output file:\tstdout.')

	contents = ''
	with open(config['file'], 'r') as f:
		contents = f.read()

	out('\n[.] Input file length: %d' % len(contents))

	obfuscator = ScriptObfuscator(
		config['normalize_only'], \
		config['custom_reserved_words'], \
		config['garbage_perc'], \
		config['min_var_length'])
	obfuscated = obfuscator.obfuscate(contents)

	if obfuscated:
		out('[.] Obfuscated file length: %d' % len(obfuscated))
		if not config['output']:
			out('\n' + '-' * 80)
			print obfuscated
			out('-' * 80)
		else:
			with open(config['output'], 'w') as f:
				f.write(obfuscated)
			out('[+] Obfuscated code has been written to: "%s"' % config['output'])
	else:
		return False


if __name__ == '__main__':
	main(sys.argv)
