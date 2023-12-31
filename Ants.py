from mnest.Environment import World, Realise
from mnest.Entities import Agent, Essence
from mnest.Laws import *
import random
import matplotlib.pyplot as plt
import numpy as np
import csv
import pandas as pd
import time
import argparse
import os

start_time = time.time()
parser = argparse.ArgumentParser(description='Run The ants simulation.')
parser.add_argument('-ns', '--no_show', action='store_true',
                    help='Activate Command Line Mode(No Visualisation)')
parser.add_argument('--start_as', type=str, default='Play', help='Weather the simulation starts (Play)ing or (Pause)d')
parser.add_argument('--sim_name', type=str, default='Default_sim', help='Name of the sim to create files and logs')
parser.add_argument('--max_steps', type=int, default=80000, help='Maximum number of steps to be taken')
parser.add_argument('--min_exploration', type=float, default=0.05)
parser.add_argument('--exploration_rate', type=float, default=0.9)
parser.add_argument('--exploration_decay', type=float, default=0.0001)
parser.add_argument('--learning_rate', type=float, default=0.4)
parser.add_argument('--discounted_return', type=float, default=0.85)
parser.add_argument('--drop_amount', type=float, default=0.05)
parser.add_argument('--dispersion_rate', type=float, default=0.1)
parser.add_argument('--decay_rate', type=float, default=0.03)

args = parser.parse_args()
"""
This is the  code file. The following is a sample template that can be modified inorder to create any type 
of simulations. This version uses inheritance to work through everything avoiding duplication and other issues.

Note : Maybe start custom variables with an _ or some identifier to prevent accidental renaming of variables.
(Or just keep in mind the parent class and not rename variables)

Run like this::
python Ants.py --no_show --start_as='Play' --max_steps=1000 --sim_name='Hope_this_works' --min_exploration=0.05 
--exploration_rate=0.9 --exploration_decay=0.0001 --learning_rate=0.4 --discounted_return=0.85
"""
random.seed(12345)
np.random.seed(12345)

# show_print = False
show_print = True
learning = True
# log = False
log = True


def progress_bar(progress, total):
    percent = 100 * (progress / total)
    bar = '*' * int(percent) + '-' * (100 - int(percent))
    print('\r' + '\033[33m' + f'|{bar}| {percent:.2f}%' + '\033[0m', end='\r')
    if progress == total:
        print('\r' + '\033[32m' + f'|{bar}| {percent:.2f}%' + '\033[0m')


class Ant(Agent):

    # Initialise the parent class. Make sure to initialise it with the child as self.
    def __init__(self, world, layer_name, position: Vector2 = Vector2(0, 0),
                 min_exploration=0.05,
                 exploration_rate=0.9,
                 exploration_decay=0.0001,
                 learning_rate=0.4,
                 discounted_return=0.85,
                 drop_amount=0.05):
        super().__init__(world=world, layer_name=layer_name, child=self, position=position,
                         action_list=['move_random', 'go_home', 'go_target', 'drop_home', 'drop_target'])
        self.has_food = False
        self.steps_since_pheromone_drop = 0
        # self.steps_since_last_food = 0  # might be usefull as a sense.

        self.home_likeness = 1  # How much the current cell is like Home according to the home pheromone
        self.target_likeness = 0  # How much the current cell is like Target according to the target pheromone
        # state_list = 'If the ant has food'+                        (True/False)
        #               'time since dropping the last pheromone.'+   (0,1,...4)
        #               'how much is the cell like home'+            (0,1,2,3,4,...9)
        #               'how much is the cell like target'           (0,1,2,3,4,...9)
        self.max_states = (2 * 5 * 5 * 5)
        self.state_hash = ''  # it is a hash that represents the state the ant exists in.

        # Environment Parameters
        self.drop_amount = drop_amount

        # Learning Parameters
        self.brain.min_exploration = min_exploration
        self.brain.exploration_rate = exploration_rate
        self.brain.exploration_decay = exploration_decay
        self.brain.learning_rate = learning_rate
        self.brain.discounted_return = discounted_return
        ################################################################################################################
        # To Provide data for analysis.
        # Consider using deque() for optimization later if needed.
        # Not storing any history as time series list as it takes up lots of memory and causes low ram systems to crash.
        # Temporary Data
        self.history = {
            'hash_history': '',  # history of the hash which caused it to select the action.
            'action_history': '',  # Actions taken per timestep.
            'state_history': '',  # State (Search Food or Search Home) achieved at this time step
            # State achieved would mean that if the ant gets back home with food,
            # The state achieved would be Search Food.
            # I'm still not sure as to what this state history would help me achieve,
            # But maybe it might come in handy.
            'food_collection_history': 0  # 1 if food was collected within this step, 0 otherwise.
        }

        # Cumulative Data
        self.cumulative = {
            'total_food_count': 0,
            'average_steps_before_collection': 0  # basically steps per food count.
        }
        ################################################################################################################
        # to populate the entire state space. This will speed up the simulation.
        full_state_table = {}
        for _ant_food in [True, False]:
            for _time_drop in [0, 1, 2, 3, 4]:
                for _like_home in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]:
                    for _like_target in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]:
                        state = (f'{_ant_food}_' +
                                 f'{_time_drop}_' +
                                 f'{_like_home}_' +
                                 f'{_like_target}')
                        # print(state)
                        full_state_table[state] = np.zeros(len(self.action_list))

        self.brain.q_table = dict(sorted(full_state_table.items()))
        ################################################################################################################

    def reset_position(self):
        self.position += (Vector2(random.choice(self.world.layers['Home'])) - self.position)
        # It has to be done this way because, the position is stored as a reference in the layer.
        # doing something like self.position = something new
        # will destroy the link between the layer and the variable. Hence, we change the referenced variable
        # and not replace it.

    def update(self):
        """
        This updates the state_hash of the ant.
        :return:
        """
        # Check Home Likeness
        if self.position in self.world.layers['Home']:
            home_likeness = 1
        else:
            home_likeness = (self.world.layers['Pheromone_Home'][int(self.position.y), int(self.position.x)] /
                             self.world.layer_data['Pheromone_Home'][3])

        # Check Target Likeness
        if self.position in self.world.layers['Target']:
            target_likeness = 1
        else:
            target_likeness = (self.world.layers['Pheromone_Target'][int(self.position.y), int(self.position.x)] /
                               self.world.layer_data['Pheromone_Target'][3])
        # self.state_hash = (f'{self.has_food}_' +
        #                    f'{self.steps_since_pheromone_drop}_' +
        #                    f'{round(home_likeness, 1):.1f}_' +
        #                    f'{round(target_likeness, 1):.1f}')

        self.state_hash = (f'{self.has_food}_' +
                           f'{self.steps_since_pheromone_drop}_' +
                           f'{round(home_likeness * 10)}_' +
                           f'{round(target_likeness * 10)}')
        # print(self.state_hash)
        # print(self.state_hash)

    def drop_pheromone(self, pheromone_type, quantity):
        pheromone_type = 'Pheromone_' + pheromone_type  # for simplicity
        self.world.layers[pheromone_type][int(self.position.y), int(self.position.x)] += quantity

        # capping pheromone at a cell to max value
        max_pheromone = self.world.layer_data[pheromone_type][3]
        pheromone_value = self.world.layers[pheromone_type][int(self.position.y), int(self.position.x)]
        if pheromone_value > max_pheromone:
            self.world.layers[pheromone_type][int(self.position.y), int(self.position.x)] = max_pheromone
            # print(w.layers['Pheromone'][0])

    def move_to_pheromone(self, pheromone_type):
        # move to the cell around it having the maximum value for the  Pheromone in the forward direction.
        aim = pheromone_type
        pheromone_type = 'Pheromone_' + pheromone_type  # for simplicity
        pheromone_layer = self.world.layers[pheromone_type]

        move_directions = []
        max_pheromone_value = 0
        # print(self.direction, DIRECTIONS)
        front_index = self.position + front(self.direction)
        front_left_index = self.position + front_left(self.direction)
        front_right_index = self.position + front_left(self.direction)

        for check_direction in [front_left_index, front_index, front_right_index]:
            if (0 <= check_direction.x < self.world.c_length) and (0 <= check_direction.y < self.world.r_length):
                # now we know the direction is possible.

                # Directly select direction if it is home or target.
                if check_direction in self.world.layers[aim]:
                    if max_pheromone_value < 2:
                        # This is the first aim cell we find.
                        # Discard all other directions.
                        move_directions = [check_direction - self.position]
                        max_pheromone_value = 2
                    else:
                        # Append new aim cells to the list.
                        move_directions = [check_direction - self.position, *move_directions]  # .

                # The following won't work once an aim cell is found.
                pheromone_value = pheromone_layer[int(check_direction.y), int(check_direction.x)]
                if pheromone_value > max_pheromone_value:
                    move_directions = [check_direction - self.position]  # we only need one direction if its max
                    max_pheromone_value = pheromone_value

                elif pheromone_value == max_pheromone_value:
                    move_directions = [check_direction - self.position, *move_directions]  # appends to the list.

        # now we have checked through all 3 forward directions.

        if len(move_directions) == 0:
            # it means there is no way forward.
            # self.direction = reflect(self.direction) This needs to be solved.
            self.direction = -self.direction

        else:
            # it means there is one or more of the directions to move towards.
            self.direction = random.choice(move_directions).copy()
            self.move()

    def move_random(self):
        self.direction = random.choice(DIRECTIONS).copy()
        self.move()

    def go_home(self):
        self.move_to_pheromone(pheromone_type='Home')

    def go_target(self):
        self.move_to_pheromone(pheromone_type='Target')

    def drop_home(self):
        self.drop_pheromone(pheromone_type='Home', quantity=self.drop_amount)

    def drop_target(self):
        self.drop_pheromone(pheromone_type='Target', quantity=self.drop_amount)


# Setting up the Visualiser.
class Visualise(Realise):
    def __init__(self, dispersion_rate, decay_rate, drop_amount, no_show, start_as, max_steps, sim_name,
                 exploration_rate, min_exploration, exploration_decay, learning_rate, discounted_return):
        # To Set up the Visualisation, Initialise the class with the World, required variables, and the one_step_loop
        # Initialise the world with necessary size and layers.
        # It is not recommended that the number of layers be more than 10
        # It Might cause errors within the visualisation.
        # The simulation will however work fine. just that the option for selecting layers will be disabled

        # Create the necessary layers.
        layers = {'Pheromone_Target': ['Float', (250, 10, 50), 'None', 1],
                  'Pheromone_Home': ['Float', (85, 121, 207), 'None', 1],
                  'Ants': ['Block', (255, 0, 0), 'Data/Stock_Images/ant_sq.png'],
                  'Home': ['Block', (50, 98, 209), 'None'],
                  'Target': ['Block', (204, 4, 37), 'None']}

        # Initialise the parent class. Make sure to initialise it with the child as self.
        # Adjust set parameters
        super().__init__(world=World(layer_data=layers, r_length=30, c_length=30), child=self,
                         visualise=not no_show, frame_rate_cap=600, cell_size=25, sim_background=(255, 255, 255))
        self.state = start_as
        self.max_steps = max_steps
        self.sim_name = sim_name
        # Set up the new variables and performing initial setups.
        tl_home = 15  # top left cell of the 2x2 home
        tl_target = 10  # top left cell of the 2x2 target
        self.world.layers['Home'] = [[tl_home, tl_home],
                                     [tl_home + 1, tl_home + 1],
                                     [tl_home, tl_home + 1],
                                     [tl_home + 1, tl_home]]
        self.world.layers['Target'] = [[tl_target, tl_target],
                                       [tl_target + 1, tl_target + 1],
                                       [tl_target, tl_target + 1],
                                       [tl_target + 1, tl_target]]

        self.ant_list = [Ant(world=self.world,
                             layer_name='Ants',
                             position=Vector2(random.choice(self.world.layers['Home'])),
                             drop_amount=drop_amount,
                             min_exploration=min_exploration,
                             exploration_rate=exploration_rate,
                             exploration_decay=exploration_decay,
                             learning_rate=learning_rate,
                             discounted_return=discounted_return,
                             ) for _ in range(30)]
        dispersion_rate = dispersion_rate  # percentage of pheromone to be dispersed.
        # calculate it like this, maybe. if 0.1 of the pheromone is to be dispersed then,

        dispersion_matrix = np.array([[dispersion_rate / 8, dispersion_rate / 8, dispersion_rate / 8],
                                      [dispersion_rate / 8, 1 - dispersion_rate, dispersion_rate / 8],
                                      [dispersion_rate / 8, dispersion_rate / 8, dispersion_rate / 8]])
        self.pheromone_a = Essence(self.world, 'Pheromone_Home', dispersion_matrix=dispersion_matrix,
                                   decay_rate=decay_rate)
        self.pheromone_b = Essence(self.world, 'Pheromone_Target', dispersion_matrix=dispersion_matrix,
                                   decay_rate=decay_rate)

        # Graphing Variables
        self.total_food_collected = 0
        self.food_collected = {}
        self.action_distribution = {}
        # {Time_step: ['move_random', 'go_home', 'go_target', 'drop_home', 'drop_target']}

        # Do not add any variables after calling the loop. it will cause object has no attribute error when used.
        self.run_sim()

    def setup_layers(self, file_path):
        # This will be added to the Realise function of the MNEST Package.

        # The csv file will contain one column with all the possible layers
        # we can uncomment and comment the layers using a #
        # As the layer is checked, the ones with the # wont match and hence wont be active.

        active_layers = []
        with open(file_path, 'r') as file:
            reader = csv.reader(file)
            for row in reader:
                active_layers += row
        # print(active_layers)
        for layer_name in self.world.layer_data:
            if layer_name in active_layers:
                self.display_layers[layer_name].active = 1
            else:
                self.display_layers[layer_name].active = 0

    def reset(self):
        for ant in self.ant_list:
            ant.has_food = False
            ant.reset_position()
        for layer_type in ['Home', 'Target']:
            self.world.layers['Pheromone_' + layer_type] *= 0
        return

    # Storing data into memory and later writing it to a file causes memory crunch and freezes the system.
    # Writing to file immediately is a better option.
    def write_to_file(self, data, file_name):
        # Include extension in file name.
        dir_path = f"Analysis/{self.sim_name}/Log"
        # Check whether the specified path exists or not
        if not os.path.exists(dir_path):
            # Create a new directory because it does not exist
            os.makedirs(dir_path)
        with open(os.path.join(dir_path, file_name), 'a') as file:
            file.write(data + '\n')

    # Create one step of the event loop that is to happen. i.e. how the world changes in one step.
    def loop_step(self):
        """
        This function is passed to the realise class to be run everytime the loop iterates.
        Basically this function is the entire set of changes that are to happen to the world.
        :return:
        """
        # # Resetting the world
        # if self.clock.time_step % 5000 == 0:
        #     self.reset()

        self.food_collected[self.clock.time_step] = np.zeros(len(self.ant_list))
        self.action_distribution[self.clock.time_step] = np.zeros(len(self.ant_list[0].action_list))
        # Iterating over all ants.
        for index, ant in enumerate(self.ant_list):

            ant.history['food_collection_history'] = 0  # For Analysis. will change using time_step.
            # Else have to repeat the 0 case multiple times.

            # use random and not np.random to use objects and not a np array.
            # if self.clock.time_step < 50000:
            if True:
                ant.sense_state('Initial')
                ant.history['hash_history'] = ant.state_hash  # For Analysis
                ant.perform_action()
                ant.history['action_history'] = ant.selected_action  # For Analysis
                ant.sense_state('Final')

                self.action_distribution[self.clock.time_step][ant.action_list.index(ant.selected_action)] += 1

                if ant.selected_action in ['drop_home', 'drop_target']:
                    ant.steps_since_pheromone_drop = 0
                else:
                    ant.steps_since_pheromone_drop = (ant.steps_since_pheromone_drop + 1) % 5

                # Check food:

                # Calculate Reward and food count.
                if ant.position in self.world.layers['Home']:
                    # Experimental, making the ant turn around at home.
                    ant.direction = -ant.direction
                    if ant.has_food:
                        reward = 100
                        # reward = 10
                        ant.has_food = False
                        ant.cumulative['total_food_count'] += 1  # For Analysis
                        ant.history['food_collection_history'] = 1  # For Analysis
                        self.food_collected[self.clock.time_step][index] = 1
                    else:
                        reward = -5
                        # reward = -1
                    ant.history['state_history'] = 'Search_Food'  # For Analysis
                    # If the ant is home then it must go to the Target.
                elif ant.position in self.world.layers['Target']:
                    # Experimental, making the ant turn around at target.
                    ant.direction = -ant.direction
                    if ant.has_food:
                        reward = -5
                        # reward = -1
                    else:
                        ant.has_food = True
                        reward = 5
                        # reward = -1
                    ant.history['state_history'] = 'Search_Home'  # For Analysis
                    # If the ant is at the Target then it must go Home.
                else:
                    reward = -1
                    # If the ant is neither at Home nor the Target, Then it must keep doing what its doing.
                    # So we do nothing about it.
                    # if this is during the first step, then its achieved state is to search for food.
                    if len(ant.history['state_history']) == 0:
                        ant.history['state_history'] = 'Search_Food'  # For Analysis
                ant.earn_reward(reward)
                if learning:
                    ant.learn()
                # We calculate the average steps taken to get to food.
                if ant.cumulative['total_food_count'] != 0:  # For Analysis
                    ant.cumulative['average_steps_before_collection'] = (self.clock.time_step + 1) / ant.cumulative[
                        'total_food_count']
                else:
                    ant.cumulative['average_steps_before_collection'] = -1
            # Now for each ant we store the history log values.
            if log:
                ant_history_data = ','.join(str(value) for value in ant.history.values())
                self.write_to_file(data=ant_history_data, file_name=f'Ant_{index}.csv')
                # Not writing brain values unless analysis is run or at the end cause else it's an overkill.

        self.pheromone_a.decay('Percentage')
        self.pheromone_b.decay('Percentage')
        self.pheromone_a.disperse()
        self.pheromone_b.disperse()

        # # Let the home and the target give off a very small amount of pheromone
        # for layer_type in ['Home', 'Target']:
        #     for position in self.world.layers[layer_type]:
        #         # print(type(self.world.layers['Pheromone_' + layer_type]))
        #         self.world.layers['Pheromone_' + layer_type][position[1], position[0]] += 0.01
        #         if self.world.layers['Pheromone_' + layer_type][position[1], position[0]] > 1:
        #             self.world.layers['Pheromone_' + layer_type][position[1], position[0]] -= 0.01

        # Writing the Cumulative data file.
        if log:
            with open(f"Analysis/{self.sim_name}/Log/Cumulative.csv", 'w') as f:
                f.write('Total_Food_Collected,Average_Steps_Before_Collection\n')
                for ant in self.ant_list:
                    f.write(f"{ant.cumulative['total_food_count']},{ant.cumulative['average_steps_before_collection']}\n")

        if show_print:
            if self.clock.time_step % 5000 == 0:
                progress_bar(self.clock.time_step, self.max_steps)

        if self.clock.time_step >= self.max_steps:
            # do not use <a>. to analyse if using kwargs.
            self.analyse()
            if show_print:
                print('Verify reproducibility by confirming this exact number.')
                print(f'Hash for this run :: {np.random.random()}')
            self.quit_sim = True
            return

    def analyse(self, **kwargs):
        ###
        # Using the analysis keybinding to reset layer visualisation.
        if self.visualise:
            self.setup_layers('Data/Layer_data.csv')
        ###
        path = "Analysis"
        # Check whether the specified path exists or not
        if not os.path.exists(path):
            # Create a new directory because it does not exist
            os.makedirs(path)

        ###############################################################################################################
        # Analysis Data Files.
        path = f"Analysis/{self.sim_name}/Log"
        # Check whether the specified path exists or not
        if not os.path.exists(path):
            # Create a new directory because it does not exist
            os.makedirs(path)
        if log:
            for index, ant in enumerate(self.ant_list):
                df = pd.DataFrame.from_dict(ant.brain.q_table, orient='index',
                                            columns=ant.action_list)
                df.index.name = 'State(HasFood_TimeSinceLstPherDrp_HomeLike_TargetLike)'
                df.reset_index(inplace=True)
                df.to_csv(f"Analysis/{self.sim_name}/Log/Ant_{index}_Brain.csv", index=False)

        ###############################################################################################################
        food = np.array(list(self.food_collected.values()))
        actions = np.array(list(self.action_distribution.values()), dtype=int)
        self.total_food_collected = np.sum(food)
        batch_size = 1000
        food_per_batch = {}
        sum_batch = np.zeros_like(food[0])
        for i, row in enumerate(food):
            sum_batch += row
            if i % batch_size == 0:
                food_per_batch[i] = sum_batch
                sum_batch = np.zeros_like(row)

        actions_per_batch = {}
        sum_batch = np.zeros_like(actions[0], dtype=int)
        for i, row in enumerate(actions):
            sum_batch += row
            if i % batch_size == 0:
                actions_per_batch[i] = sum_batch
                sum_batch = np.zeros_like(row, dtype=int)

        fig_1 = plt.figure(1)
        food_per_batch_values = np.array(list(food_per_batch.values()))
        food_per_batch_values = np.sum(food_per_batch_values, axis=1)
        plt.plot(food_per_batch.keys(), food_per_batch_values, '-.')
        plt.title(f'Food Collected per {batch_size} Steps')
        plt.xlabel('Time Step')
        plt.ylabel('Counts')
        plt.legend([f'Food/{batch_size} steps'])
        plt.ylim(0, 300)
        fig_1.savefig('Analysis/' + self.sim_name + f'_foodper{batch_size}' + '.png')
        plt.close(fig_1)

        fig_2 = plt.figure(2)
        actions_per_batch_values = np.array(list(actions_per_batch.values()))

        # Define the names of the actions
        action_names = self.ant_list[0].action_list

        # Compute the cumulative sums of the action counts for each time step
        cumulative_counts = np.cumsum(actions_per_batch_values, axis=1)
        # Create a stacked bar plot
        for i in range(len(action_names) - 1, -1, -1):
            plt.plot(range(cumulative_counts.shape[0]), cumulative_counts[:, i], '-.')
        plt.legend(action_names)
        plt.title(f'Action Distribution per {batch_size} Steps')
        plt.xlabel(f'Time Step (x{batch_size})')
        plt.ylabel('Counts')
        fig_2.savefig('Analysis/' + self.sim_name + f'_actionper{batch_size}_' + '.png')
        if show_print:
            print(self.sim_name + ' Completed!')
        plt.close(fig_2)


# To run the following only if this is the main program.
# To avoid running this when parallel code call this as an import.

if __name__ == "__main__":
    # Instantiating the realisation/ Gods Perspective
    realise = Visualise(dispersion_rate=args.dispersion_rate,
                        decay_rate=args.decay_rate,
                        drop_amount=args.drop_amount,
                        min_exploration=args.min_exploration,
                        exploration_rate=args.exploration_rate,
                        exploration_decay=args.exploration_decay,
                        learning_rate=args.learning_rate,
                        discounted_return=args.discounted_return,
                        no_show=args.no_show,
                        start_as=args.start_as,
                        max_steps=args.max_steps,
                        sim_name=args.sim_name)
    end_time = time.time()
    if show_print:
        print(f'Time for execution :: {end_time - start_time}s')
