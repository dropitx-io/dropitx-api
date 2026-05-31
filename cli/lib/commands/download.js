const chalk = require('chalk');
const ora = require('ora');
const { downloadFile } = require('../api');

module.exports = function(program) {
  program
    .command('download <url>')
    .description('Download a shared file')
    .option('-o, --output <path>', 'Output file path')
    .action(async (url, options) => {
      const spinner = ora('Downloading...').start();
      
      try {
        // Extract slug from URL or use as-is
        let slug = url;
        
        // Handle different URL formats
        if (url.includes('/s/')) {
          // Format: https://dropitx.com/s/abc123
          const match = url.match(/\/s\/([^\/\?]+)/);
          if (match) {
            slug = match[1];
          }
        } else if (url.includes('dropitx')) {
          // Try to extract slug from any dropitx URL
          const parts = url.split('/');
          slug = parts[parts.length - 1];
        }
        
        spinner.text = `Downloading ${slug}...`;
        const result = await downloadFile(slug, options.output);
        
        spinner.succeed(chalk.green('Download successful!'));
        console.log('');
        console.log(chalk.cyan('Saved to:'), result.path);
        console.log(chalk.cyan('Filename:'), result.filename);
      } catch (error) {
        spinner.fail(chalk.red(`Download failed: ${error.message}`));
        process.exit(1);
      }
    });
};
