from setuptools import setup

if __name__ == '__main__':
    setup(
        name='nba-etl',
        version='0.0.1',
        author='Zach Kazanski',
        author_email='kazanski.zachary@gmail.com',
        description='Scrapes and calculates PER of NBA players in realtime',
        url="https://github.com/hivelocity/hivelocity-etl",
        py_modules=['nba_etl'],
        install_requires=[
            'click==6.6'
        ],
        entry_points='''
            [console_scripts]
            nba-etl=nba_etl:cmds
        ''',
        classifiers=[
            'Programming Language :: Python',
            'Intended Audience :: Developers',
            'Operating System :: OS Independent',
            'Programming Language :: Python',
        ],
    )
