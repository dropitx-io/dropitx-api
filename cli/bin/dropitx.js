#!/usr/bin/env node

const { Command } = require('commander');
const chalk = require('chalk');
const pkg = require('../package.json');

const program = new Command();

program
  .name('dropitx')
  .description('DropItX CLI - Share files from terminal')
  .version(pkg.version);

// Load commands
require('../lib/commands/login')(program);
require('../lib/commands/upload')(program);
require('../lib/commands/download')(program);
require('../lib/commands/list')(program);
require('../lib/commands/delete')(program);

program.parse();
