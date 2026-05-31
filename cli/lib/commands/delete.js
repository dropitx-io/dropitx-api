const chalk = require('chalk');
const ora = require('ora');
const { deleteDocument } = require('../api');

module.exports = function(program) {
  program
    .command('delete <url>')
    .description('Delete a shared file')
    .option('-f, --force', 'Skip confirmation')
    .action(async (url, options) => {
      // Extract slug from URL
      let slug = url;
      
      if (url.includes('/s/')) {
        const match = url.match(/\/s\/([^\/\?]+)/);
        if (match) {
          slug = match[1];
        }
      } else if (url.includes('dropitx')) {
        const parts = url.split('/');
        slug = parts[parts.length - 1];
      }
      
      // Confirm deletion
      if (!options.force) {
        const readline = require('readline');
        const rl = readline.createInterface({
          input: process.stdin,
          output: process.stdout,
        });
        
        const question = (query) => new Promise((resolve) => rl.question(query, resolve));
        
        try {
          const answer = await question(chalk.yellow(`Delete ${slug}? (y/N): `));
          if (answer.toLowerCase() !== 'y') {
            console.log(chalk.gray('Cancelled.'));
            return;
          }
        } finally {
          rl.close();
        }
      }
      
      const spinner = ora('Deleting...').start();
      
      try {
        await deleteDocument(slug);
        spinner.succeed(chalk.green('Document deleted successfully'));
      } catch (error) {
        spinner.fail(chalk.red(`Delete failed: ${error.message}`));
        process.exit(1);
      }
    });
};
