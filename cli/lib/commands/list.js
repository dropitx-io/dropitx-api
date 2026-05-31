const chalk = require('chalk');
const ora = require('ora');
const { listDocuments } = require('../api');

module.exports = function(program) {
  program
    .command('list')
    .description('List your shared files')
    .option('-p, --page <n>', 'Page number', '1')
    .option('-l, --limit <n>', 'Items per page', '20')
    .option('-j, --json', 'Output as JSON')
    .action(async (options) => {
      const spinner = ora('Loading documents...').start();
      
      try {
        const page = parseInt(options.page);
        const limit = parseInt(options.limit);
        
        const documents = await listDocuments(page, limit);
        
        spinner.succeed(chalk.green(`Found ${documents.length} documents`));
        
        if (options.json) {
          console.log(JSON.stringify(documents, null, 2));
        } else {
          if (documents.length === 0) {
            console.log(chalk.gray('\nNo documents found.'));
            return;
          }
          
          console.log('');
          console.log(chalk.cyan.bold('Your Documents:'));
          console.log(chalk.gray('─'.repeat(80)));
          
          documents.forEach((doc, index) => {
            const num = chalk.gray(`${(page - 1) * limit + index + 1}.`);
            const title = doc.title || doc.filename || doc.slug;
            const slug = chalk.gray(`[${doc.slug}]`);
            const views = chalk.gray(`${doc.view_count} views`);
            const date = new Date(doc.created_at).toLocaleDateString();
            
            console.log(`${num} ${chalk.white(title)} ${slug}`);
            console.log(`   ${chalk.gray(date)} • ${views}`);
            
            if (doc.burn_after_reading) {
              console.log(`   ${chalk.yellow('⚠ Burn after reading')}`);
            }
            if (doc.expires_at) {
              const expires = new Date(doc.expires_at);
              if (expires > new Date()) {
                console.log(`   ${chalk.gray(`Expires: ${expires.toLocaleDateString()}`)}`);
              } else {
                console.log(`   ${chalk.red('Expired')}`);
              }
            }
            console.log('');
          });
          
          if (documents.length === limit) {
            console.log(chalk.gray(`Use --page ${page + 1} to see more`));
          }
        }
      } catch (error) {
        spinner.fail(chalk.red(`Failed to list documents: ${error.message}`));
        process.exit(1);
      }
    });
};
